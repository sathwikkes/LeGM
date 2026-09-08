from sqlalchemy import create_engine, inspect, text

from legm.data.db import init_db, sync_columns
from legm.data.models import Base


def test_init_db_adds_missing_columns(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url, future=True)
    # Simulate a database created before the injury columns existed.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE players (nba_id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, normalized_name VARCHAR(120) NOT NULL, team VARCHAR(8), age FLOAT, nba_position VARCHAR(8), yahoo_positions VARCHAR(32))"))
        conn.execute(text("INSERT INTO players (nba_id, name, normalized_name) VALUES (1, 'A', 'a')"))
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("players")}
    assert {"injury_status", "injury_note"} <= cols
    with engine.begin() as conn:
        assert conn.execute(text("SELECT injury_status FROM players WHERE nba_id = 1")).scalar() is None
    assert sync_columns(engine, Base.metadata) == []  # idempotent
