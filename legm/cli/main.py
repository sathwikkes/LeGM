"""legm command-line interface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from legm.cli.draft import draft_app
from legm.config import load_league_config
from legm.data.crosswalk import load_yahoo_positions
from legm.data.csv_io import load_adp_csv, load_injuries_csv, load_projection_csv, read_csv
from legm.data.db import init_db, make_engine, session_scope
from legm.data.ingest import ingest_seasons
from legm.data.nba import DEFAULT_RAW_DIR, DEFAULT_SLEEP_SECONDS, GAME_TYPES, RawCache, season_schedule
from legm.data.schedule import (
    DEFAULT_SCHEDULE_DIR,
    read_schedule_csv,
    schedule_path,
    upsert_games,
    write_schedule_csv,
)
from legm.engine.rankings import RANK_COLUMNS, rank_players

app = typer.Typer(help="LeGM: deterministic fantasy NBA draft engine.", no_args_is_help=True)
console = Console()
app.add_typer(draft_app, name="draft")

ConfigOpt = Annotated[Path | None, typer.Option("--config", help="Path to league.yaml (default config/league.yaml or $LEGM_CONFIG)")]
DbOpt = Annotated[str | None, typer.Option("--db", help="SQLAlchemy URL (default sqlite:///data/legm.db or $LEGM_DATABASE_URL)")]


def _engine(db: str | None):
    engine = make_engine(db)
    init_db(engine)
    return engine


def _report_unmatched(unmatched: pd.DataFrame, what: str) -> None:
    if unmatched.empty:
        return
    console.print(f"[yellow]{len(unmatched)} {what} rows did not match a player:[/yellow]")
    label = "name" if "name" in unmatched.columns else "nba_id"
    for value in unmatched[label].head(25):
        console.print(f"  - {value}")
    if len(unmatched) > 25:
        console.print(f"  ... and {len(unmatched) - 25} more")


@app.callback()
def _root(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")


@app.command()
def ingest(
    seasons: Annotated[list[str], typer.Option("--seasons", help="Seasons like 2024-25 2025-26")],
    more_seasons: Annotated[list[str] | None, typer.Argument(hidden=True)] = None,
    raw_dir: Annotated[Path, typer.Option(help="Raw response cache directory")] = DEFAULT_RAW_DIR,
    sleep: Annotated[float, typer.Option(help="Seconds between live nba_api calls")] = DEFAULT_SLEEP_SECONDS,
    config: ConfigOpt = None,
    db: DbOpt = None,
) -> None:
    """Pull season stats via nba_api (cached under data/raw) and build v0 projections."""
    all_seasons = [*seasons, *(more_seasons or [])]  # `--seasons 2024-25 2025-26` works
    league = load_league_config(config)
    cache = RawCache(raw_dir=raw_dir, sleep_seconds=sleep)
    with session_scope(_engine(db)) as session:
        report = ingest_seasons(session, all_seasons, cache, league.projection)
    console.print(
        f"Ingested seasons {', '.join(report.seasons)}: "
        f"{report.players_upserted} players, {report.season_rows_upserted} season rows, "
        f"{report.projections_built} v0 projections ({report.live_calls} live API calls).",
        soft_wrap=True,
    )


@app.command("ingest-schedule")
def ingest_schedule(
    season: Annotated[str, typer.Option("--season", help="Season like 2025-26")],
    raw_dir: Annotated[Path, typer.Option(help="Raw response cache directory")] = DEFAULT_RAW_DIR,
    schedule_dir: Annotated[Path, typer.Option(help="Where the slim CSV is written")] = DEFAULT_SCHEDULE_DIR,
    sleep: Annotated[float, typer.Option(help="Seconds between live nba_api calls")] = DEFAULT_SLEEP_SECONDS,
    season_types: Annotated[
        list[str] | None,
        typer.Option("--season-type", help=f"Game types to keep (default: regular). One of: {', '.join(sorted(set(GAME_TYPES.values())))}"),
    ] = None,
    db: DbOpt = None,
) -> None:
    """Pull the NBA schedule via nba_api, write the slim CSV, and store the games."""
    if season_types and (bad := sorted(set(season_types) - set(GAME_TYPES.values()))):
        console.print(f"[red]Unknown season type(s): {', '.join(bad)}[/red]")
        raise typer.Exit(code=1)
    cache = RawCache(raw_dir=raw_dir, sleep_seconds=sleep)
    frame = season_schedule(season, cache, season_types or None)
    if frame.empty:
        console.print(f"[red]No games parsed for {season}.[/red]")
        raise typer.Exit(code=1)
    path = write_schedule_csv(frame, schedule_path(season, schedule_dir))
    with session_scope(_engine(db)) as session:
        added = upsert_games(session, frame, season)
    console.print(
        f"{season}: {len(frame)} games -> {path} ({added} new, {len(frame) - added} already stored).",
        soft_wrap=True,
    )


@app.command("load-schedule")
def load_schedule(
    file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    season: Annotated[str | None, typer.Option("--season", help="Season label (default: the file stem)")] = None,
    db: DbOpt = None,
) -> None:
    """Load a schedule CSV (columns: game_date, home_team, away_team)."""
    try:
        frame = read_schedule_csv(file)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    with session_scope(_engine(db)) as session:
        added = upsert_games(session, frame, season or file.stem)
    console.print(f"Loaded {added} new games from {file.name} ({len(frame)} rows).", soft_wrap=True)


@app.command("load-projections")
def load_projections(file: Annotated[Path, typer.Argument(exists=True, readable=True)], db: DbOpt = None) -> None:
    """Load an external projection CSV; it takes precedence over v0_blend."""
    with session_scope(_engine(db)) as session:
        loaded, unmatched = load_projection_csv(session, file)
    console.print(f"Loaded {loaded} projections from {file.name}.", soft_wrap=True)
    _report_unmatched(unmatched, "projection")


@app.command("load-adp")
def load_adp(file: Annotated[Path, typer.Argument(exists=True, readable=True)], db: DbOpt = None) -> None:
    """Load an ADP CSV (columns: name or nba_id, adp)."""
    with session_scope(_engine(db)) as session:
        loaded, unmatched = load_adp_csv(session, file)
    console.print(f"Loaded ADP for {loaded} players from {file.name}.", soft_wrap=True)
    _report_unmatched(unmatched, "ADP")


@app.command("load-injuries")
def load_injuries(file: Annotated[Path, typer.Argument(exists=True, readable=True)], db: DbOpt = None) -> None:
    """Load an injury report CSV (columns: name or nba_id, status, note). Replaces the previous report."""
    with session_scope(_engine(db)) as session:
        loaded, unmatched = load_injuries_csv(session, file)
    console.print(f"Loaded injury status for {loaded} players from {file.name}.", soft_wrap=True)
    _report_unmatched(unmatched, "injury")


@app.command("load-positions")
def load_positions(file: Annotated[Path, typer.Argument(exists=True, readable=True)], db: DbOpt = None) -> None:
    """Load Yahoo position eligibility (columns: name or nba_id, positions like 'PG,SG')."""
    with session_scope(_engine(db)) as session:
        updated, unmatched = load_yahoo_positions(session, read_csv(file))
    console.print(f"Updated Yahoo positions for {updated} players from {file.name}.", soft_wrap=True)
    _report_unmatched(unmatched, "position")


@app.command()
def rank(
    top: Annotated[int, typer.Option(help="Rows to print")] = 50,
    include_inactive: Annotated[bool, typer.Option(help="Include players with no games in the latest season")] = False,
    csv: Annotated[Path | None, typer.Option(help="Also write the full table to this CSV")] = None,
    config: ConfigOpt = None,
    db: DbOpt = None,
) -> None:
    """Print deterministic rankings by VORP."""
    league = load_league_config(config)
    with session_scope(_engine(db)) as session:
        ranked = rank_players(session, league, include_inactive=include_inactive)
    if ranked.empty:
        console.print("[red]No projections found. Run `legm ingest` first.[/red]")
        raise typer.Exit(code=1)
    if csv is not None:
        ranked[RANK_COLUMNS + ["SOURCE"]].to_csv(csv, index=False)

    levels = ranked.attrs.get("replacement_levels", {})
    table = Table(title=f"LeGM rankings — {league.league.name} ({league.league.num_teams} teams)")
    for col in RANK_COLUMNS:
        table.add_column(col, justify="right" if col not in ("NAME", "POSITIONS", "TEAM") else "left")
    for _, r in ranked.head(top).iterrows():
        table.add_row(
            str(int(r["RANK"])),
            str(r["NAME"]),
            str(r["POSITIONS"]),
            str(r["TEAM"] or ""),
            f"{r['GP']:.0f}",
            f"{r['FPG']:.1f}",
            f"{r['SEASON_FP']:.0f}",
            f"{r['VORP']:.0f}",
            "" if r["ADP"] is None or pd.isna(r["ADP"]) else f"{r['ADP']:.1f}",
        )
    console.print(table)
    if levels:
        console.print("Replacement levels (season FP): " + ", ".join(f"{k} {v:.0f}" for k, v in levels.items()))


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes")] = False,
) -> None:
    """Run the HTTP/WebSocket API (uvicorn)."""
    import uvicorn

    uvicorn.run("legm.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
