import shutil
from pathlib import Path

from typer.testing import CliRunner

from legm.cli.main import app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIG = Path(__file__).resolve().parents[2] / "config" / "league.yaml"
runner = CliRunner()


def _ingest(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    shutil.copytree(FIXTURES, raw)
    db = f"sqlite:///{tmp_path / 'legm.db'}"
    monkeypatch.setattr("legm.data.nba._fetch_player_stats", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    monkeypatch.setattr("legm.data.nba._fetch_player_index", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    r = runner.invoke(app, ["ingest", "--seasons", "2024-25", "2025-26", "--raw-dir", str(raw), "--config", str(CONFIG), "--db", db])
    assert r.exit_code == 0, r.output
    return db


def test_draft_lifecycle(tmp_path, monkeypatch):
    db = _ingest(tmp_path, monkeypatch)
    ddir = str(tmp_path / "drafts")
    # 3 active fixture players; use a 2-team, 1-round config so the draft is tiny.
    cfg = tmp_path / "league.yaml"
    cfg.write_text(CONFIG.read_text().replace("num_teams: 8", "num_teams: 2").replace(
        "slots: [PG, SG, G, SF, PF, F, C, C, UTIL, UTIL]", "slots: [UTIL]").replace("bench: 3", "bench: 0"))
    base = ["--draft-dir", ddir]

    r = runner.invoke(app, ["draft", "new", "--name", "t1", "--user-slot", "2", "--config", str(cfg), "--db", db, *base])
    assert r.exit_code == 0, r.output
    assert "Created draft 't1' with 3 players" in r.output
    assert "Team 1 on the clock" in r.output and "Your next pick: #2" in r.output

    r = runner.invoke(app, ["draft", "pick", "jokic", *base])
    assert r.exit_code == 0, r.output
    assert "Team 1 selects Nikola Jokić" in r.output
    assert "Team 2 (YOU) on the clock" in r.output

    r = runner.invoke(app, ["draft", "pick", "jokic", *base])
    assert r.exit_code == 1 and "already drafted" in r.output and "pick 1, Team 1" in r.output
    r = runner.invoke(app, ["draft", "pick", "zzz", *base])
    assert r.exit_code == 1 and "no available player" in r.output

    r = runner.invoke(app, ["draft", "status", *base])
    assert r.exit_code == 0, r.output
    assert "Jaren Jackson Jr." in r.output and "Nikola Jokić" not in r.output

    r = runner.invoke(app, ["draft", "undo", *base])
    assert r.exit_code == 0 and "Undid pick 1" in r.output
    r = runner.invoke(app, ["draft", "undo", *base])
    assert r.exit_code == 1

    r = runner.invoke(app, ["draft", "sim", "--until-user", *base])
    assert r.exit_code == 0 and "Simulated 1 picks" in r.output
    r = runner.invoke(app, ["draft", "board", *base])
    assert r.exit_code == 0 and "Jokić" in r.output
    r = runner.invoke(app, ["draft", "sim", *base])
    assert r.exit_code == 0 and "Draft complete" in r.output
    r = runner.invoke(app, ["draft", "list", *base])
    assert "t1: 2/2 picks" in r.output


def test_ambiguous_and_missing_draft(tmp_path):
    r = runner.invoke(app, ["draft", "status", "--draft-dir", str(tmp_path)])
    assert r.exit_code == 1 and "No drafts" in r.output


def test_draft_new_num_teams(tmp_path, monkeypatch):
    runner = CliRunner()
    db = _ingest(tmp_path, monkeypatch)
    ddir = str(tmp_path / "drafts")
    cfg = tmp_path / "league.yaml"
    cfg.write_text(CONFIG.read_text().replace("num_teams: 8", "num_teams: 2").replace(
        "slots: [PG, SG, G, SF, PF, F, C, C, UTIL, UTIL]", "slots: [UTIL]").replace("bench: 3", "bench: 0"))
    base = ["--draft-dir", ddir, "--config", str(cfg), "--db", db]

    r = runner.invoke(app, ["draft", "new", "--name", "t3", "--user-slot", "3", "--num-teams", "3", *base])
    assert r.exit_code == 0, r.output
    assert "Your next pick: #3" in r.output
    r = runner.invoke(app, ["draft", "board", "--draft", "t3", "--draft-dir", ddir])
    assert r.exit_code == 0 and "Team 3" in r.output

    # 4 teams x 1 round needs 4 players; only 3 fixture players are active
    r = runner.invoke(app, ["draft", "new", "--name", "t4", "--user-slot", "1", "--num-teams", "4", *base])
    assert r.exit_code == 1 and "too few for 4 teams" in r.output
