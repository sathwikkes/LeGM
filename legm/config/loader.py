"""Load config/league.yaml into a LeagueConfig."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from legm.config.models import LeagueConfig

DEFAULT_CONFIG_PATH = Path("config") / "league.yaml"
CONFIG_ENV_VAR = "LEGM_CONFIG"


def resolve_config_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path is not None:
        return Path(path)
    if env := os.environ.get(CONFIG_ENV_VAR):
        return Path(env)
    return DEFAULT_CONFIG_PATH


def load_league_config(path: str | os.PathLike[str] | None = None) -> LeagueConfig:
    config_path = resolve_config_path(path)
    with open(config_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return LeagueConfig.model_validate(raw)
