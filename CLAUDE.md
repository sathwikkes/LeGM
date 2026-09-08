# LeGM — Fantasy NBA draft assistant (Yahoo H2H points)

SPEC.md is authoritative. Read it before proposing changes.
Build ONLY the phase named in the current prompt. Deterministic engine before anything LLM.

Stack: Python 3.12 + uv, FastAPI, SQLAlchemy (SQLite dev, Postgres later), pandas/numpy, pytest.
Frontend (later phases): Next.js + TypeScript.

Rules:
- Never hard-code scoring, roster slots, or team count outside config/league.yaml.
- Raw stat projections and fantasy-point math stay separate.
- No LLM call in any code path the live draft depends on.
- Every engine function is a pure function with a unit test.
- Cache raw external data under data/raw/; never re-download what is cached.
- Commit after each green test run.

Commands: uv run pytest · uv run legm --help