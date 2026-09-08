import shutil
from pathlib import Path

from typer.testing import CliRunner

from legm.cli.main import app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIG = Path(__file__).resolve().parents[2] / "config" / "league.yaml"

runner = CliRunner()


def test_ingest_then_rank_and_loads(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    shutil.copytree(FIXTURES, raw)
    db = f"sqlite:///{tmp_path / 'legm.db'}"
    monkeypatch.setattr("legm.data.nba._fetch_player_stats", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    monkeypatch.setattr("legm.data.nba._fetch_player_index", lambda s: (_ for _ in ()).throw(AssertionError("live")))

    r = runner.invoke(app, ["ingest", "--seasons", "2024-25", "--seasons", "2025-26", "--raw-dir", str(raw), "--config", str(CONFIG), "--db", db])
    assert r.exit_code == 0, r.output
    assert "0 live API calls" in r.output

    out_csv = tmp_path / "rank.csv"
    r = runner.invoke(app, ["rank", "--top", "2", "--config", str(CONFIG), "--db", db, "--csv", str(out_csv)])
    assert r.exit_code == 0, r.output
    assert "Nikola Jokić" in r.output and "Rookie Guard" not in r.output
    assert out_csv.read_text().count("\n") == 4  # header + 3 active players

    adp = tmp_path / "adp.csv"
    adp.write_text("name,adp\nNikola Jokic,1\nMystery Man,50\n")
    r = runner.invoke(app, ["load-adp", str(adp), "--db", db])
    assert r.exit_code == 0 and "Mystery Man" in r.output

    pos = tmp_path / "pos.csv"
    pos.write_text("name,positions\nJaren Jackson Jr.,PF/C\n")
    r = runner.invoke(app, ["load-positions", str(pos), "--db", db])
    assert r.exit_code == 0 and "Updated Yahoo positions for 1" in r.output

    r = runner.invoke(app, ["rank", "--top", "5", "--config", str(CONFIG), "--db", db])
    assert r.exit_code == 0
    assert "PF,C" in r.output and "1.0" in r.output


def test_rank_empty_db_exits_nonzero(tmp_path):
    r = runner.invoke(app, ["rank", "--config", str(CONFIG), "--db", f"sqlite:///{tmp_path / 'x.db'}"])
    assert r.exit_code == 1


def test_load_schedule_cli(tmp_path, monkeypatch):
    db = f"sqlite:///{tmp_path / 'legm.db'}"
    csv = tmp_path / "2025-26.csv"
    csv.write_text("game_date,home_team,away_team\n2025-10-21,AAA,BBB\n2025-10-22,BBB,CCC\n")
    r = CliRunner().invoke(app, ["load-schedule", str(csv), "--db", db])
    assert r.exit_code == 0, r.output
    assert "Loaded 2 new games" in r.output
    # re-running stores nothing new
    r = CliRunner().invoke(app, ["load-schedule", str(csv), "--db", db])
    assert r.exit_code == 0 and "Loaded 0 new games" in r.output

    bad = tmp_path / "bad.csv"
    bad.write_text("game_date\n2025-10-21\n")
    r = CliRunner().invoke(app, ["load-schedule", str(bad), "--db", db])
    assert r.exit_code == 1 and "missing column" in r.output


def test_ingest_schedule_cli(tmp_path, monkeypatch):
    """Reads the cached fixture payload; a live call would fail the test."""
    db = f"sqlite:///{tmp_path / 'legm.db'}"
    monkeypatch.setattr("legm.data.nba._fetch_schedule", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    out = tmp_path / "schedule"
    r = CliRunner().invoke(
        app,
        ["ingest-schedule", "--season", "2025-26", "--raw-dir", str(FIXTURES),
         "--schedule-dir", str(out), "--db", db],
    )
    assert r.exit_code == 0, r.output
    # 3 regular-season games; the preseason and playoff rows are filtered out
    assert "2025-26: 3 games" in r.output and "(3 new, 0 already stored)" in r.output
    assert (out / "2025-26.csv").exists()

    r = CliRunner().invoke(
        app,
        ["ingest-schedule", "--season", "2025-26", "--raw-dir", str(FIXTURES),
         "--schedule-dir", str(out), "--season-type", "nonsense", "--db", db],
    )
    assert r.exit_code == 1 and "Unknown season type" in r.output
