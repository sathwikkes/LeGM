from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from legm.api.app import Settings, create_app
from legm.api.auth import AuthSettings
from legm.cli.main import app as cli

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIG = Path(__file__).resolve().parents[2] / "config" / "league.yaml"


@pytest.fixture
def client(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    shutil.copytree(FIXTURES, raw)
    db = f"sqlite:///{tmp_path / 'legm.db'}"
    monkeypatch.setattr("legm.data.nba._fetch_player_stats", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    monkeypatch.setattr("legm.data.nba._fetch_player_index", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    r = CliRunner().invoke(cli, ["ingest", "--seasons", "2024-25", "2025-26", "--raw-dir", str(raw), "--config", str(CONFIG), "--db", db])
    assert r.exit_code == 0, r.output
    # 2 teams, tiny roster so the 3-player fixture pool can complete a draft.
    cfg = tmp_path / "league.yaml"
    cfg.write_text(
        CONFIG.read_text()
        .replace("num_teams: 8", "num_teams: 2")
        .replace("slots: [PG, SG, G, SF, PF, F, C, C, UTIL, UTIL]", "slots: [UTIL]")
        .replace("bench: 3", "bench: 0")
    )
    app = create_app(Settings(config_path=cfg, database_url=db, auth=AuthSettings(secret="test-secret-" + "x" * 32, invite_code=None)))
    with TestClient(app) as c:
        r = c.post("/api/auth/register", json={"email": "me@example.com", "password": "hunter22!", "display_name": "Me"})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        c.token = r.json()["access_token"]
        yield c
