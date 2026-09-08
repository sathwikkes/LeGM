from pathlib import Path

import pytest
from pydantic import ValidationError

from legm.config import Position, load_league_config
from legm.config.models import LeagueConfig, RosterConfig

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config" / "league.yaml"


def test_repo_config_defaults():
    cfg = load_league_config(REPO_CONFIG)
    assert cfg.league.num_teams == 8
    assert cfg.league.draft_type == "snake"
    assert cfg.league.format == "h2h_points"
    assert cfg.roster.slots == ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "UTIL", "UTIL"]
    assert cfg.roster.bench == 3 and cfg.roster.il == 1
    assert cfg.scoring.weights() == {
        "PTS": 1.0, "REB": 1.2, "AST": 1.5, "STL": 3.0, "BLK": 3.0, "TOV": -1.0
    }
    assert cfg.projection.season_weights == [0.65, 0.35]
    assert cfg.projection.gp_cap == 72
    assert cfg.roster.slot_positions("G") == (Position.PG, Position.SG)
    assert cfg.roster.slot_positions("C") == (Position.C,)


def test_env_var_override(tmp_path, monkeypatch):
    p = tmp_path / "x.yaml"
    p.write_text(REPO_CONFIG.read_text().replace("num_teams: 8", "num_teams: 12"))
    monkeypatch.setenv("LEGM_CONFIG", str(p))
    assert load_league_config().league.num_teams == 12


def test_unknown_scoring_key_rejected():
    raw = {
        "league": {"num_teams": 8},
        "roster": {"slots": ["PG"], "bench": 0, "il": 0},
        "scoring": {"PTS": 1, "DUNKS": 5},
        "projection": {"season_weights": [1.0], "gp_cap": 72},
    }
    with pytest.raises(ValidationError):
        LeagueConfig.model_validate(raw)


def test_unresolvable_slot_rejected():
    with pytest.raises(ValidationError):
        RosterConfig(slots=["PG", "FLEX"], bench=0, il=0)
