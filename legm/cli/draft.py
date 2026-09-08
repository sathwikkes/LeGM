"""`legm draft ...` commands. State lives in data/drafts/<id>.json between invocations."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from legm.config import load_league_config
from legm.data.db import init_db, make_engine, session_scope
from legm.data.names import normalize_name
from legm.data.schedule import games_on, has_schedule, teams_playing_on
from legm.draft.models import DraftState, PlayerCard
from legm.draft.persistence import DEFAULT_DRAFT_DIR, list_drafts, load_draft, save_draft
from legm.draft.pool import load_pool, pool_shortfall
from legm.draft.simulate import simulate
from legm.draft.state import (
    DraftError,
    available,
    available_frame,
    current_pick,
    current_round,
    is_complete,
    make_pick,
    new_draft,
    picks_before_user,
    team_on_the_clock,
    team_roster,
    undo,
    user_next_pick,
)
from legm.draft.roster import build_slots
from legm.draft.strategies import STRATEGIES, make_strategy
from legm.engine.lineup import optimize_lineup, player_days

draft_app = typer.Typer(help="Live draft state: new, pick, undo, status, board, sim, lineup.", no_args_is_help=True)
# NBA game dates are Eastern; a UTC clock would roll over during West-coast games.
NBA_TZ = ZoneInfo("America/New_York")
console = Console()

DraftDirOpt = Annotated[Path, typer.Option("--draft-dir", help="Where draft JSON files live")]
DraftOpt = Annotated[str | None, typer.Option("--draft", help="Draft id (default: most recently modified)")]


def _load(draft_id: str | None, directory: Path) -> DraftState:
    if draft_id is None:
        ids = list_drafts(directory)
        if not ids:
            console.print("[red]No drafts found. Run `legm draft new` first.[/red]")
            raise typer.Exit(code=1)
        draft_id = ids[0]
    try:
        return load_draft(draft_id, directory)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


def resolve_player(state: DraftState, query: str) -> PlayerCard:
    """Match an available player by nba_id, exact normalized name, or unique substring."""
    avail = available(state)
    if query.strip().isdigit():
        pid = int(query)
        for c in avail:
            if c.player_id == pid:
                return c
        raise DraftError(f"no available player with id {pid}")
    q = normalize_name(query)
    exact = [c for c in avail if normalize_name(c.name) == q]
    if len(exact) == 1:
        return exact[0]
    partial = [c for c in avail if q in normalize_name(c.name)]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        taken = [c for pid, c in state.pool.items() if q in normalize_name(c.name)]
        if taken:
            by = {p.player_id: p for p in state.picks}
            hints = ", ".join(
                f"{c.name} (pick {by[c.player_id].pick_number}, {state.config.team_names[by[c.player_id].team_index]})"
                for c in taken[:5] if c.player_id in by
            )
            raise DraftError(f"{query!r} already drafted: {hints}")
        raise DraftError(f"no available player matches {query!r}")
    names = ", ".join(f"{c.name} ({c.player_id})" for c in partial[:8])
    raise DraftError(f"{query!r} is ambiguous: {names}")


def _clock_line(state: DraftState) -> str:
    if is_complete(state):
        return "Draft complete."
    team = team_on_the_clock(state)
    you = " (YOU)" if team == state.config.user_team_index else ""
    return (
        f"Pick {current_pick(state)} / round {current_round(state)}: "
        f"{state.config.team_names[team]}{you} on the clock. "
        f"Your next pick: #{user_next_pick(state)} ({picks_before_user(state)} picks away)."
    )


@draft_app.command()
def new(
    name: Annotated[str, typer.Option(help="Draft id (file name)")],
    user_slot: Annotated[int, typer.Option(help="Your draft slot, 1-based")],
    num_teams: Annotated[int | None, typer.Option(help="Teams in this draft (default: config league.num_teams)")] = None,
    team_names: Annotated[str | None, typer.Option(help="Comma-separated team names")] = None,
    include_inactive: Annotated[bool, typer.Option()] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    db: Annotated[str | None, typer.Option("--db")] = None,
    draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR,
) -> None:
    """Start a draft from the current rankings."""
    league = load_league_config(config)
    engine = make_engine(db)
    init_db(engine)
    with session_scope(engine) as session:
        pool = load_pool(session, league, include_inactive=include_inactive)
    if not pool:
        console.print("[red]Empty player pool. Run `legm ingest` first.[/red]")
        raise typer.Exit(code=1)
    if num_teams is not None and (short := pool_shortfall(pool, league, num_teams)):
        console.print(f"[red]{short}. Run `legm ingest` or lower --num-teams.[/red]")
        raise typer.Exit(code=1)
    names = [n.strip() for n in team_names.split(",")] if team_names else None
    try:
        state = new_draft(
            league, pool, user_team_index=user_slot - 1, team_names=names, draft_id=name, num_teams=num_teams
        )
    except DraftError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    path = save_draft(state, draft_dir)
    console.print(f"Created draft {name!r} with {len(pool)} players -> {path}", soft_wrap=True)
    console.print(_clock_line(state), soft_wrap=True)


@draft_app.command()
def pick(
    player: Annotated[str, typer.Argument(help="Player name (fuzzy) or nba_id")],
    draft: DraftOpt = None,
    draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR,
) -> None:
    """Record the pick for the team on the clock."""
    state = _load(draft, draft_dir)
    try:
        card = resolve_player(state, player)
        team = team_on_the_clock(state)
        state = make_pick(state, card.player_id)
    except DraftError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    save_draft(state, draft_dir)
    console.print(
        f"Pick {state.picks[-1].pick_number}: {state.config.team_names[team]} selects "
        f"{card.name} ({','.join(p.value for p in card.positions)}, {card.team}).",
        soft_wrap=True,
    )
    console.print(_clock_line(state), soft_wrap=True)


@draft_app.command("undo")
def undo_cmd(draft: DraftOpt = None, draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR) -> None:
    """Remove the most recent pick."""
    state = _load(draft, draft_dir)
    try:
        last = state.picks[-1] if state.picks else None
        state = undo(state)
    except DraftError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    save_draft(state, draft_dir)
    console.print(f"Undid pick {last.pick_number}: {state.pool[last.player_id].name} is available again.", soft_wrap=True)
    console.print(_clock_line(state), soft_wrap=True)


@draft_app.command()
def status(
    top: Annotated[int, typer.Option(help="Available players to show")] = 15,
    draft: DraftOpt = None,
    draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR,
) -> None:
    """Clock, your roster, and the best available (VORP recomputed on the remaining pool)."""
    state = _load(draft, draft_dir)
    console.print(_clock_line(state), soft_wrap=True)
    roster = team_roster(state, state.config.user_team_index)
    t = Table(title=f"Your roster — {roster.name}")
    t.add_column("Slot")
    t.add_column("Player")
    t.add_column("Pos")
    for slot, pid in roster.slots.items():
        if pid is None:
            t.add_row(slot, "-", "")
        else:
            c = state.pool[pid]
            t.add_row(slot, c.name, ",".join(p.value for p in c.positions))
    console.print(t)
    console.print(
        "Open starting positions: " + (", ".join(p.value for p in roster.open_positions) or "none")
        + f" | open bench: {roster.open_bench}",
        soft_wrap=True,
    )
    frame = available_frame(state)
    t = Table(title=f"Best available (top {top})")
    for col in ("NAME", "POSITIONS", "TEAM", "GP", "FPG", "SEASON_FP", "VORP", "ADP"):
        t.add_column(col, justify="left" if col in ("NAME", "POSITIONS", "TEAM") else "right")
    for _, r in frame.head(top).iterrows():
        t.add_row(
            r["NAME"], r["POSITIONS"], str(r["TEAM"] or ""), f"{r['GP']:.0f}", f"{r['FPG']:.1f}",
            f"{r['SEASON_FP']:.0f}", f"{r['VORP']:.0f}",
            "" if r["ADP"] is None or pd.isna(r["ADP"]) else f"{r['ADP']:.1f}",
        )
    console.print(t)


@draft_app.command()
def lineup(
    date: Annotated[str | None, typer.Option(help="YYYY-MM-DD (default: today, US Eastern)")] = None,
    team: Annotated[int | None, typer.Option(help="Team index (default: yours)")] = None,
    draft: DraftOpt = None,
    draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR,
    db: Annotated[str | None, typer.Option("--db")] = None,
) -> None:
    """Best legal lineup for a date: FP/G x P(play), for players whose team is playing."""
    state = _load(draft, draft_dir)
    team_index = state.config.user_team_index if team is None else team
    if not 0 <= team_index < state.config.num_teams:
        console.print(f"[red]--team must be in [0, {state.config.num_teams}).[/red]")
        raise typer.Exit(code=1)
    try:
        day = date_cls.fromisoformat(date) if date else datetime.now(NBA_TZ).date()
    except ValueError:
        console.print("[red]--date must be YYYY-MM-DD.[/red]")
        raise typer.Exit(code=1) from None

    roster = team_roster(state, team_index)
    cards = {pid: state.pool[pid] for pid in roster.player_ids}
    engine = make_engine(db)
    init_db(engine)
    with session_scope(engine) as session:
        opponents = teams_playing_on(session, day)
        loaded = has_schedule(session)
        games = len(games_on(session, day))
    if not loaded:
        console.print("[yellow]No schedule stored. Run `legm ingest-schedule --season 2025-26` first.[/yellow]")

    result = optimize_lineup(player_days(cards, opponents, state.league.lineup), build_slots(state.league), day)
    t = Table(title=f"{roster.name} — {day.isoformat()} ({games} games scheduled)")
    for col, justify in (("Slot", "left"), ("Player", "left"), ("Pos", "left"), ("Opp", "left"),
                         ("FP/G", "right"), ("P(play)", "right"), ("xFP", "right")):
        t.add_column(col, justify=justify)
    for slot in result.slots:
        p = slot.player
        if p is None:
            t.add_row(slot.slot, "[dim]-[/dim]", "", "", "", "", "")
        else:
            t.add_row(
                slot.slot, p.name, ",".join(x.value for x in p.positions), p.opponent or "",
                f"{p.fpg:.1f}", f"{p.play_probability:.0%}", f"{p.expected_points:.1f}",
            )
    console.print(t)
    console.print(
        f"Expected: [bold]{result.expected_points:.1f}[/bold] FP "
        f"(raw {result.raw_points:.1f}) from {len(result.starters)} starters."
        + (f" Empty: {', '.join(result.empty_slots)}." if result.empty_slots else ""),
        soft_wrap=True,
    )
    if result.bench:
        labels = {"no_game": "no game", "ruled_out": "ruled out", "outscored": "no slot"}
        t = Table(title="Bench")
        for col in ("Player", "Pos", "Reason", "xFP"):
            t.add_column(col, justify="right" if col == "xFP" else "left")
        for b in result.bench:
            t.add_row(b.player.name, ",".join(x.value for x in b.player.positions),
                      labels[b.reason], f"{b.player.expected_points:.1f}")
        console.print(t)
        console.print(f"Points left on the bench (lineup congestion): {result.points_left_on_bench:.1f} FP.", soft_wrap=True)


@draft_app.command()
def board(draft: DraftOpt = None, draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR) -> None:
    """Snake grid of every pick so far."""
    state = _load(draft, draft_dir)
    cfg = state.config
    t = Table(title=f"Draft board — {state.draft_id}")
    t.add_column("Rd", justify="right")
    for i, name in enumerate(cfg.team_names):
        t.add_column(f"{name}{' *' if i == cfg.user_team_index else ''}")
    by_pick = {p.pick_number: p for p in state.picks}
    from legm.draft.order import round_team_to_pick

    for rnd in range(1, cfg.rounds + 1):
        row = [str(rnd)]
        for team in range(cfg.num_teams):
            p = by_pick.get(round_team_to_pick(rnd, team, cfg.num_teams))
            row.append("" if p is None else state.pool[p.player_id].name.split(" ", 1)[-1])
        t.add_row(*row)
    console.print(t)
    console.print(_clock_line(state), soft_wrap=True)


@draft_app.command()
def sim(
    strategy: Annotated[str, typer.Option(help=f"Opponent strategy: {', '.join(sorted(STRATEGIES))}")] = "needs",
    jitter: Annotated[int, typer.Option(help="Pick uniformly among the top-N candidates")] = 1,
    seed: Annotated[int, typer.Option()] = 0,
    until_user: Annotated[bool, typer.Option(help="Stop when you are on the clock")] = False,
    draft: DraftOpt = None,
    draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR,
) -> None:
    """Let simulated opponents (and, unless --until-user, you) pick."""
    state = _load(draft, draft_dir)
    before = len(state.picks)
    try:
        state = simulate(state, default=make_strategy(strategy, jitter), seed=seed, stop_before_user=until_user)
    except (DraftError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    save_draft(state, draft_dir)
    for p in state.picks[before:]:
        c = state.pool[p.player_id]
        console.print(f"  {p.pick_number:>3} R{p.round:<2} {state.config.team_names[p.team_index]:<12} {c.name}", soft_wrap=True)
    console.print(f"Simulated {len(state.picks) - before} picks.", soft_wrap=True)
    console.print(_clock_line(state), soft_wrap=True)


@draft_app.command("list")
def list_cmd(draft_dir: DraftDirOpt = DEFAULT_DRAFT_DIR) -> None:
    """Saved drafts, most recent first."""
    ids = list_drafts(draft_dir)
    if not ids:
        console.print("No drafts saved.")
    for d in ids:
        s = load_draft(d, draft_dir)
        console.print(f"{d}: {len(s.picks)}/{s.config.total_picks} picks", soft_wrap=True)
