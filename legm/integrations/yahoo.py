"""Yahoo Fantasy Sports adapter (Phase 8, scaffold).

Yahoo's draft results endpoint is
    GET https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/draftresults?format=json
authenticated with an OAuth2 bearer token. Obtaining that token needs a Yahoo
developer app and a browser consent flow, so this adapter takes an already
issued access token and a league key. Player names come from a second call to
    GET .../league/{league_key}/players;player_keys=...
which this scaffold batches.

Nothing in the live draft depends on this module: if it fails, manual entry
and the file source keep working.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable

from legm.integrations.base import ExternalPick

BASE = "https://fantasysports.yahooapis.com/fantasy/v2"


def _default_fetch(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode("utf-8"))


def parse_draft_results(payload: dict) -> list[dict]:
    """Flatten Yahoo's nested draftresults JSON into [{pick, round, team_key, player_key}]."""
    out = []
    try:
        league = payload["fantasy_content"]["league"]
        results = next(part["draft_results"] for part in league if isinstance(part, dict) and "draft_results" in part)
    except (KeyError, StopIteration, TypeError):
        return out
    for key, item in results.items():
        if key == "count" or not isinstance(item, dict):
            continue
        dr = item.get("draft_result", {})
        if "player_key" in dr:
            out.append({"pick": int(dr["pick"]), "round": int(dr["round"]), "team_key": dr["team_key"], "player_key": dr["player_key"]})
    return sorted(out, key=lambda r: r["pick"])


def parse_player_names(payload: dict) -> dict[str, str]:
    """player_key -> full name from a league/players response."""
    names: dict[str, str] = {}
    try:
        league = payload["fantasy_content"]["league"]
        players = next(part["players"] for part in league if isinstance(part, dict) and "players" in part)
    except (KeyError, StopIteration, TypeError):
        return names
    for key, item in players.items():
        if key == "count" or not isinstance(item, dict):
            continue
        pkey = full = None
        for part in item.get("player", [[]])[0]:
            if isinstance(part, dict):
                pkey = part.get("player_key", pkey)
                if "name" in part:
                    full = part["name"].get("full")
        if pkey and full:
            names[pkey] = full
    return names


class YahooSource:
    name = "yahoo"

    def __init__(self, league_key: str, access_token: str, fetch: Callable[[str, str], dict] = _default_fetch):
        self.league_key = league_key
        self.token = access_token
        self.fetch = fetch

    def poll(self) -> list[ExternalPick]:
        results = parse_draft_results(self.fetch(f"{BASE}/league/{self.league_key}/draftresults?format=json", self.token))
        if not results:
            return []
        keys = ",".join(r["player_key"] for r in results)
        names = parse_player_names(self.fetch(f"{BASE}/league/{self.league_key}/players;player_keys={keys}?format=json", self.token))
        return [
            ExternalPick(pick_number=r["pick"], player_name=names.get(r["player_key"], r["player_key"]), team_name=r["team_key"], source="yahoo")
            for r in results
        ]
