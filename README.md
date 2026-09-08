# LeGM — Phase 1: player database, scoring engine, deterministic rankings

```bash
uv sync
uv run legm ingest --seasons 2024-25 2025-26   # nba_api, cached under data/raw/
uv run legm rank --top 50                      # VORP rankings
uv run legm load-projections file.csv          # external projections override v0_blend
uv run legm load-adp file.csv                  # ADP column
uv run legm load-positions file.csv            # Yahoo eligibility (see below)
uv run pytest
```

All scoring, roster, team-count and projection parameters live in `config/league.yaml`
(`--config` or `$LEGM_CONFIG` to override). Database defaults to `sqlite:///data/legm.db`
(`--db` or `$LEGM_DATABASE_URL`).

## Data model

- `players`: nba_id, name, normalized_name, team, age, nba_position, yahoo_positions (nullable).
- `season_stats`: per-game GP, MPG, PTS, REB, AST, STL, BLK, TOV, FGM, FGA, FTM, FTA, FG3M per player-season.
- `projections`: same stat columns plus `source` (`v0_blend` or `csv:<file>`). Fantasy points are
  never stored; they are computed from the scoring config at rank time.
- `adp`: one row per player, replaced on every `load-adp`.

## Projection v0

Per-game rates are a blend of the configured seasons with effective weight
`nominal_weight × total_minutes`; projected GP is `min(gp_cap, nominal-weighted mean GP)`.
Players with no games in the most recent season are excluded from `rank` unless
`--include-inactive` is passed or a CSV projection exists for them.

## Position eligibility

`yahoo_positions` is authoritative once loaded. Until then the NBA.com label falls back to:

| NBA | Yahoo   |
|-----|---------|
| G   | PG, SG  |
| F   | SF, PF  |
| C   | C       |
| G-F | SG, SF  |
| F-G | SF, SG  |
| F-C | PF, C   |
| C-F | C, PF   |

## CSV formats

Rows match on `nba_id` when present, else on normalized `name`. Unmatched rows are listed.

- projections: `name, gp, mpg, pts, reb, ast, stl, blk, tov` (+ optional `fgm, fga, ftm, fta, fg3m`)
- adp: `name, adp`
- positions: `name, positions` (e.g. `PG,SG` or `PG/SG`)

## VORP

Replacement level for position P = the `(num_teams × starting slots a P-eligible player can fill)`-th
best season FP among P-eligible players. Multi-position players count toward each position.
VORP = season FP − lowest replacement level among the player's eligible positions.

# Phase 2: DraftState and simulated snake draft

```bash
uv run legm draft new --name mydraft --user-slot 4      # pool from current rankings
uv run legm draft new --name big --user-slot 3 --num-teams 12   # override the configured league size
uv run legm draft pick "jokic"                          # fuzzy name or nba_id; team on the clock
uv run legm draft undo
uv run legm draft status --top 15                       # clock, your roster, best available
uv run legm draft board
uv run legm draft sim --until-user --strategy needs --jitter 3 --seed 1
uv run legm draft sim                                   # finish the draft with simulated picks
uv run legm draft list
```

Drafts persist as JSON under `data/drafts/<name>.json` (`--draft NAME` selects one; the
most recently modified is the default). The pool is a snapshot of the rankings at
`draft new`, so a live draft never depends on the database.

`league.num_teams` in `config/league.yaml` is the *default* team count. `--num-teams` (and the
Teams selector on the web form, and `num_teams` in `POST /api/drafts`) overrides it for one
draft, 2 to 20. The override is snapshotted onto that draft's own league config, so replacement
levels, positional scarcity and opponent modelling all follow it — every per-draft computation
reads `state.league`, never the process-wide config.

- `DraftState` is immutable: `make_pick` and `undo` return new states. Rosters are derived
  from the pick log, so undo is exact.
- Roster legality is a maximum bipartite matching of players to starting slots; unmatched
  players go to the bench, and IL slots are never draftable. Earlier players keep their
  slot when a free one serves the newcomer, and shift (PG -> G) only when required.
- `status` recomputes replacement levels and VORP on the remaining pool.
- Strategies: `best_available` (VORP), `adp` (lowest ADP, then VORP), `needs` (best
  available who fills an open starting slot). `--jitter N` picks uniformly among the top N
  candidates under a fixed `--seed`, so mock drafts vary but reproduce.

# Phase 3: API

```bash
uv run legm serve --port 8000          # FastAPI + WebSocket; docs at http://localhost:8000/docs
```

| Method | Path | Purpose |
|---|---|---|
| GET | /api/league | league config summary |
| GET | /api/players?q=&position=&top=&include_inactive= | rankings |
| GET | /api/drafts · POST /api/drafts | list / create (`{name, user_slot, team_names?}`) |
| GET, DELETE | /api/drafts/{id} | full draft view / delete |
| GET | /api/drafts/{id}/available?q=&position=&limit=&offset= | remaining pool, VORP recomputed, legality flags |
| GET | /api/drafts/{id}/recommendations?top=3 | deterministic v0 recommendations with components and reasons |
| POST | /api/drafts/{id}/picks `{player_id}` | pick for the team on the clock |
| POST | /api/drafts/{id}/undo | remove last pick |
| POST | /api/drafts/{id}/simulate `{strategy, jitter, seed, until_user}` | let strategies pick |
| WS | /ws/drafts/{id} | receives `{type:"draft", draft}` on connect and after every change |

Drafts are stored as JSON files (`LEGM_DRAFT_DIR`, default data/drafts). Engine errors map to 409,
validation to 422. CORS allows `LEGM_CORS_ORIGINS` (default localhost:3000).

# Phase 4: Web UI

```bash
cd web && npm install && npm run dev   # http://localhost:3000, expects the API on :8000
```

Set `NEXT_PUBLIC_API_URL` to point elsewhere (see web/.env.local.example).

- `/` create and open drafts; `/rankings` player explorer; `/draft/[id]` the draft room.
- Draft room: clock bar with Undo / Sim to my pick / Sim rest, three recommendation cards,
  searchable available table (`/` focuses search, arrows move, Enter drafts, Esc clears),
  roster panel for any team, snake board and pick log. Live updates over the WebSocket with
  polling fallback when the socket is down.

# Phases 5–8 and accounts

## Accounts (sharing the app)

Email + password accounts with JWT bearer tokens. Rankings are public; drafts, recommendations,
feedback and the assistant require a signed-in user, and every draft belongs to the user who
created it (stored in the `drafts` table as a JSON blob, so SQLite and Postgres both work).

- `POST /api/auth/register` `{email, password, display_name, invite_code?}` · `POST /api/auth/login` · `GET /api/auth/me`
- Set `LEGM_SECRET_KEY` before exposing the server; set `LEGM_INVITE_CODE` to gate sign-ups.
- The WebSocket takes the token as `?token=`.
- Existing databases are upgraded additively on startup (`init_db` adds missing columns).

## Monte Carlo survival and opponent model (`legm/sim`)

Opponents pick the lowest *noisy consensus rank*: ADP when loaded, else pool-VORP rank, plus
Gaussian noise (`simulation.adp_sigma`) and a bonus for filling an open starting slot
(`simulation.needs_bonus`). `survival()` runs `simulation.n_sims` vectorized drafts of the picks
between now and your next turn and reports P(available) per candidate. Results are cached per
draft moment. `GET /api/drafts/{id}/survival`, `GET /api/drafts/{id}/opponents`.

## Draft Opportunity Score (`legm/engine/opportunity.py`)

```
score = 100 * ( w.value*value + w.fit*fit + w.scarcity*scarcity + w.gp*gp + w.upside*upside
              + w.adp*adp_value - w.injury*injury - w.uncertainty*(1-confidence)
              - w.return * p_return * value )
```

Weights live under `recommendation.weights` in `config/league.yaml`. Every component is returned
by `GET /api/drafts/{id}/recommendations` and `GET /api/drafts/{id}/compare?ids=a,b,c`.

## Feedback and preferences

`POST /api/drafts/{id}/feedback {player_id, vote}` stores the vote with the player's components
and nudges the user's preferences (risk tolerance, rookie/veteran/upside preference, injury
aversion, ADP sensitivity) by 0.1 per vote. Preferences scale the weights by up to ±50%
(`legm/engine/opportunity.py::effective_weights`). `GET/PUT /api/preferences`.

## Assistant (`legm/agent`)

`POST /api/drafts/{id}/chat {messages}` runs a Claude tool-use loop over the deterministic tools
(`get_draft_state`, `get_my_roster`, `get_available_players`, `get_player_projection`,
`get_player_value`, `compare_players`, `get_roster_needs`, `get_position_scarcity`,
`simulate_until_next_pick`, `get_probability_of_return`, `get_opponent_rosters`,
`get_injury_context`, `generate_ranked_recommendations`, `optimize_lineup`). The model never
computes numbers.
Without `ANTHROPIC_API_KEY` the endpoint returns 503 and the UI shows the assistant as offline;
everything else keeps working.

## Integrations (`legm/integrations`)

`DraftSource` adapters yield `ExternalPick`s that are applied through the normal `make_pick`
validation, so the local state stays authoritative. Included: `ManualSource`, `FileSource`
(CSV/JSON written by a browser companion), and a `YahooSource` scaffold that takes a league key
and an OAuth access token. `POST /api/drafts/{id}/import-picks {format, content}` and the
"Import picks" button apply a pasted CSV/JSON in order from the current pick.

## Injuries

`uv run legm load-injuries file.csv` (columns: name or nba_id, status, note) replaces the injury
report; status feeds the DOS injury penalty and is shown in the UI.

# Phase 9: NBA schedule and the daily lineup optimizer

```bash
uv run legm ingest-schedule --season 2025-26     # nba_api -> data/schedule/2025-26.csv + games table
uv run legm load-schedule data/schedule/2025-26.csv --season 2025-26   # offline path, e.g. in the container
uv run legm draft lineup --draft mydraft --date 2025-12-25             # best legal lineup that day
```

Once a roster is set, the optimizer answers "who do I start tonight?". For a given date it takes
the players whose NBA team is playing, discounts each by the chance they suit up, and fills the
starting slots to maximize

```
expected points = FP/G x P(play)
```

`P(play)` comes from `lineup.play_probability` in `config/league.yaml`, keyed by injury status
(`out: 0`, `doubtful: 0.25`, `questionable: 0.5`, `probable: 0.9`). Statuses are matched
case-insensitively and anything unlisted falls back to `default_probability`, so an unrecognised
status never silently benches a player.

The result is exact, not a heuristic: sets of players that can be matched to distinct starting
slots form a transversal matroid, so offering players in descending expected-points order to the
same augmenting-path matcher the draft uses yields a maximum-weight basis. `tests/engine/test_lineup.py`
checks that against exhaustive brute force on 25 randomised rosters.

Every benched player is labelled `no_game`, `ruled_out` or `outscored`, and the response reports
**points left on the bench** — expected production lost to lineup congestion rather than to the
schedule or an injury. That is the "usable fantasy points" figure SPEC.md asks for under Roster Fit.

`GET /api/drafts/{id}/lineup?date=YYYY-MM-DD&team=N` (both optional; date defaults to today in US
Eastern, team to yours) and the **Optimize lineup** panel in the draft room. `schedule_loaded`
distinguishes "nobody plays today" from "no schedule has been ingested".

## Schedule data

`ingest-schedule` reads `scheduleleaguev2`, which answers with nested JSON rather than the
`resultSets` shape the other endpoints use. The raw payload is ~4.5MB of broadcaster metadata, so
it is **gitignored**; the 41KB slim CSV it writes (`data/schedule/<season>.csv`) is committed
instead, and `load-schedule` reads it back so ingest stays offline inside the container.

A season payload also carries preseason games (some against non-NBA clubs like MEL and HAP),
All-Star, the NBA Cup final, the play-in and the playoffs — none of which score fantasy points.
Every game stores its type, parsed from the NBA game-id prefix, and both ingest and the day
queries default to the regular season: 1230 games, 30 teams, 82 each. `--season-type` overrides.

### Known limitations

- Projections are season-long per-game averages. There is no opponent or matchup adjustment, so
  "best combo" means the best expected FP/G combination, not a true nightly projection.
- Injury status comes only from the manual `legm load-injuries` CSV; there is no live feed, so
  stale injury data yields stale lineups.
- Back-to-backs, minutes restrictions and rest days are not modelled.

# Docker and deployment

```bash
cp .env.example .env            # set LEGM_SECRET_KEY at minimum
docker compose up --build       # Postgres + API (:8000) + web (:3000)
docker compose run --rm api legm ingest --seasons 2024-25 2025-26
```

Standalone images: `docker build -t legm-api .` and
`docker build -t legm-web --build-arg NEXT_PUBLIC_API_URL=https://your-api -f web/Dockerfile web`.
The API image expects `LEGM_DATABASE_URL` (SQLite under `/app/data` by default, or Postgres) and
serves HTTP plus the WebSocket on `$PORT` (default 8000). The raw nba_api cache in `data/raw` is
committed and copied into the image, so `legm ingest --seasons 2024-25 2025-26` works inside the
deployed container (for example Railway's Console tab) with zero network calls. To refresh player
data, delete `data/raw`, run ingest locally, and commit the new cache.

CI (`.github/workflows/ci.yml`) runs pytest, the web lint/typecheck/build, and both Docker builds.
