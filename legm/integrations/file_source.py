"""File-based source: a browser companion (or a human) writes picks to a CSV/JSON file
and the API imports them. Columns/keys: pick_number, player_name, optional player_id, team_name."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from legm.integrations.base import ExternalPick


def parse_picks_text(text: str, fmt: str) -> list[ExternalPick]:
    rows: list[dict] = []
    if fmt == "json":
        data = json.loads(text)
        rows = data["picks"] if isinstance(data, dict) else data
    elif fmt == "csv":
        rows = list(csv.DictReader(text.splitlines()))
    else:
        raise ValueError("fmt must be 'csv' or 'json'")
    out = []
    for r in rows:
        r = {str(k).strip().lower(): v for k, v in r.items()}
        name = r.get("player_name") or r.get("player") or r.get("name")
        if not name or r.get("pick_number") in (None, ""):
            continue
        pid = r.get("player_id") or r.get("nba_id")
        out.append(
            ExternalPick(
                pick_number=int(r["pick_number"]),
                player_name=str(name).strip(),
                player_id=int(pid) if pid not in (None, "") else None,
                team_name=(str(r["team_name"]).strip() if r.get("team_name") else None),
                source="file",
            )
        )
    return out


class FileSource:
    name = "file"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def poll(self) -> list[ExternalPick]:
        if not self.path.exists():
            return []
        fmt = "json" if self.path.suffix.lower() == ".json" else "csv"
        return parse_picks_text(self.path.read_text(encoding="utf-8"), fmt)
