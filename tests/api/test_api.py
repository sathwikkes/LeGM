import pytest
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "league.yaml"
from starlette.websockets import WebSocketDisconnect


def test_health_and_league(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    league = client.get("/api/league").json()
    assert league["num_teams"] == 2 and league["scoring"]["REB"] == 1.2


def test_players(client):
    players = client.get("/api/players").json()
    assert [p["name"] for p in players] == ["Nikola Jokić", "Jaren Jackson Jr.", "Rookie Guard"]
    assert client.get("/api/players", params={"q": "jokic"}).json()[0]["player_id"] == 1
    assert [p["name"] for p in client.get("/api/players", params={"position": "C"}).json()] == ["Nikola Jokić", "Jaren Jackson Jr."]
    assert client.get("/api/players/1").json()["positions"] == ["C"]
    assert client.get("/api/players/999").status_code == 404
    assert len(client.get("/api/players", params={"include_inactive": "true"}).json()) == 4


def test_draft_lifecycle(client):
    r = client.post("/api/drafts", json={"name": "d1", "user_slot": 2})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["clock"] == {
        "current_pick": 1, "current_round": 1, "team_on_the_clock": 0, "team_name_on_the_clock": "Team 1",
        "is_user_turn": False, "user_next_pick": 2, "picks_before_user": 1, "is_complete": False, "total_picks": 2,
    }
    assert d["config"]["slots"] == ["UTIL", "IL1"]
    assert client.post("/api/drafts", json={"name": "d1", "user_slot": 2}).status_code == 409
    assert client.post("/api/drafts", json={"name": "bad name!", "user_slot": 2}).status_code == 422
    assert client.post("/api/drafts", json={"name": "d2", "user_slot": 9}).status_code == 422
    assert [s["draft_id"] for s in client.get("/api/drafts").json()] == ["d1"]

    avail = client.get("/api/drafts/d1/available").json()
    assert avail["total"] == 3 and avail["players"][0]["name"] == "Nikola Jokić"
    assert avail["players"][0]["legal_for_user"] and avail["players"][0]["fills_open_slot"]

    recs = client.get("/api/drafts/d1/recommendations").json()
    assert recs["for_team"] == 0 and not recs["is_user_turn"] and recs["until_pick"] == 2
    top = recs["recommendations"][0]
    assert top["player"]["name"] == "Nikola Jokić" and top["rank"] == 1 and top["reasons"]
    assert 0.0 <= top["components"]["p_return"] <= 1.0 and top["score"] == top["components"]["score"]
    assert set(recs["scarcity"]) == {"PG", "SG", "SF", "PF", "C"}
    assert "p_return" in avail["players"][0] and avail["players"][0]["p_return"] is not None

    r = client.post("/api/drafts/d1/picks", json={"player_id": 1})
    assert r.status_code == 200
    d = r.json()
    assert d["picks"][0]["player"]["name"] == "Nikola Jokić" and d["clock"]["is_user_turn"]
    assert d["rosters"][0]["slots"][0]["player"]["player_id"] == 1 and d["rosters"][0]["open_bench"] == 0
    assert client.post("/api/drafts/d1/picks", json={"player_id": 1}).status_code == 409
    assert client.post("/api/drafts/d1/picks", json={"player_id": 4242}).status_code == 409

    assert client.get("/api/drafts/d1/available").json()["total"] == 2
    r = client.post("/api/drafts/d1/undo")
    assert r.status_code == 200 and r.json()["picks"] == []
    assert client.post("/api/drafts/d1/undo").status_code == 409

    r = client.post("/api/drafts/d1/simulate", json={"strategy": "needs", "jitter": 1, "seed": 0, "until_user": True})
    assert r.status_code == 200 and r.json()["clock"]["is_user_turn"]
    assert client.post("/api/drafts/d1/simulate", json={"strategy": "chaos"}).status_code == 422
    r = client.post("/api/drafts/d1/simulate", json={"until_user": False})
    assert r.json()["clock"]["is_complete"]
    assert client.get("/api/drafts/d1").json()["clock"]["is_complete"]
    assert client.get("/api/drafts").json()[0]["is_complete"]

    assert client.delete("/api/drafts/d1").status_code == 204
    assert client.get("/api/drafts/d1").status_code == 404
    assert client.delete("/api/drafts/d1").status_code == 404


def test_websocket_receives_updates(client):
    client.post("/api/drafts", json={"name": "ws1", "user_slot": 1})
    with client.websocket_connect(f"/ws/drafts/ws1?token={client.token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "draft" and first["draft"]["clock"]["current_pick"] == 1
        client.post("/api/drafts/ws1/picks", json={"player_id": 1})
        update = ws.receive_json()
        assert update["draft"]["picks"][0]["player"]["player_id"] == 1
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/drafts/nope?token={client.token}"):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/drafts/ws1?token=bad"):
            pass


def test_auth_flow(client):
    anon = client.__class__(client.app)
    assert anon.get("/api/drafts").status_code == 401
    assert anon.get("/api/players").status_code == 200  # rankings are public
    assert anon.get("/api/auth/me").status_code == 401
    r = anon.post("/api/auth/register", json={"email": "Me@Example.com", "password": "hunter22!", "display_name": "Dup"})
    assert r.status_code == 409
    r = anon.post("/api/auth/register", json={"email": "short@example.com", "password": "short", "display_name": "S"})
    assert r.status_code == 422
    r = anon.post("/api/auth/login", json={"email": "me@example.com", "password": "wrong"})
    assert r.status_code == 401
    r = anon.post("/api/auth/login", json={"email": "ME@example.com", "password": "hunter22!"})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Me"
    anon.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert anon.get("/api/auth/me").json()["email"] == "me@example.com"
    anon.headers["Authorization"] = "Bearer nope"
    assert anon.get("/api/auth/me").status_code == 401


def test_drafts_are_per_user(client):
    client.post("/api/drafts", json={"name": "mine", "user_slot": 1})
    other = client.__class__(client.app)
    r = other.post("/api/auth/register", json={"email": "you@example.com", "password": "password1", "display_name": "You"})
    other.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert other.get("/api/drafts").json() == []
    assert other.get("/api/drafts/mine").status_code == 404
    # Same name is fine for a different user.
    assert other.post("/api/drafts", json={"name": "mine", "user_slot": 2}).status_code == 201
    assert client.get("/api/drafts/mine").json()["config"]["user_team_index"] == 0
    assert other.get("/api/drafts/mine").json()["config"]["user_team_index"] == 1


def test_invite_code(tmp_path):
    from legm.api.app import Settings, create_app
    from legm.api.auth import AuthSettings
    from fastapi.testclient import TestClient

    app = create_app(Settings(config_path=CONFIG_PATH, database_url=f"sqlite:///{tmp_path / 'i.db'}", auth=AuthSettings(secret="s" * 32, invite_code="LETMEIN")))
    with TestClient(app) as c:
        assert c.get("/api/auth/config").json() == {"invite_required": True}
        body = {"email": "a@b.co", "password": "password1", "display_name": "A"}
        assert c.post("/api/auth/register", json=body).status_code == 403
        assert c.post("/api/auth/register", json={**body, "invite_code": "LETMEIN"}).status_code == 201


def test_survival_opponents_compare_feedback(client):
    client.post("/api/drafts", json={"name": "s1", "user_slot": 2})
    surv = client.get("/api/drafts/s1/survival").json()
    assert surv["from_pick"] == 1 and surv["until_pick"] == 2
    assert [p["team_index"] for p in surv["picks_between"]] == [0]
    by_id = {e["player"]["player_id"]: e["p_return"] for e in surv["players"]}
    assert by_id[1] < 0.7 and by_id[1] == min(by_id.values())  # Jokic is the consensus #1 with one opponent picking first
    opp = client.get("/api/drafts/s1/opponents").json()
    assert opp["until_pick"] == 2 and opp["opponents"][0]["team_index"] == 0
    assert opp["opponents"][0]["likely_targets"][0]["player"]["player_id"] == 1
    cmp_ = client.get("/api/drafts/s1/compare", params={"ids": "1,2"}).json()
    assert [p["player"]["player_id"] for p in cmp_["players"]] == [1, 2]
    assert cmp_["players"][0]["components"]["score"] is not None
    assert client.get("/api/drafts/s1/compare", params={"ids": "1"}).status_code == 422
    assert client.get("/api/drafts/s1/compare", params={"ids": "x"}).status_code == 422

    assert client.get("/api/preferences").json()["injury_aversion"] == 0.0
    r = client.post("/api/drafts/s1/feedback", json={"player_id": 3, "vote": 1})  # rookie guard, age 20
    assert r.status_code == 200, r.text
    assert r.json()["rookie_preference"] == pytest.approx(0.1)
    r = client.post("/api/drafts/s1/feedback", json={"player_id": 3, "vote": -1})
    assert r.json()["rookie_preference"] == pytest.approx(0.0)
    assert client.post("/api/drafts/s1/feedback", json={"player_id": 3, "vote": 0}).status_code == 422
    assert client.post("/api/drafts/s1/feedback", json={"player_id": 999, "vote": 1}).status_code == 404
    r = client.put("/api/preferences", json={"risk_tolerance": 5, "injury_aversion": -0.4})
    assert r.json()["risk_tolerance"] == 1.0 and r.json()["injury_aversion"] == -0.4


def test_llm_status_and_chat_offline(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    st = client.get("/api/llm/status").json()
    assert st["available"] is False and "get_my_roster" in st["tools"]
    client.post("/api/drafts", json={"name": "c1", "user_slot": 1})
    r = client.post("/api/drafts/c1/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503


def test_chat_with_stub_client(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from legm.api.app import Settings, create_app
    from legm.api.auth import AuthSettings
    from legm.cli.main import app as cli

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    raw = tmp_path / "raw"
    shutil.copytree(fixtures, raw)
    db = f"sqlite:///{tmp_path / 'legm.db'}"
    monkeypatch.setattr("legm.data.nba._fetch_player_stats", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    monkeypatch.setattr("legm.data.nba._fetch_player_index", lambda s: (_ for _ in ()).throw(AssertionError("live")))
    CliRunner().invoke(cli, ["ingest", "--seasons", "2024-25", "2025-26", "--raw-dir", str(raw), "--config", str(CONFIG_PATH), "--db", db])

    class Stub:
        def __init__(self):
            self.messages = SimpleNamespace(create=self.create)
            self.n = 0

        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                return SimpleNamespace(content=[SimpleNamespace(type="tool_use", id="t1", name="generate_ranked_recommendations", input={"top": 2})], stop_reason="tool_use", usage=None)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Model says: take Jokic.")], stop_reason="end_turn", usage=None)

    app = create_app(Settings(config_path=CONFIG_PATH, database_url=db, auth=AuthSettings(secret="s" * 32)), llm_client=Stub())
    with TestClient(app) as c:
        tok = c.post("/api/auth/register", json={"email": "z@z.co", "password": "password1", "display_name": "Z"}).json()["access_token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        assert c.get("/api/llm/status").json()["available"] is True
        c.post("/api/drafts", json={"name": "c2", "user_slot": 1})
        r = c.post("/api/drafts/c2/chat", json={"messages": [{"role": "user", "content": "who?"}]})
        assert r.status_code == 200, r.text
        assert r.json()["reply"].startswith("Model says") and r.json()["tool_calls"][0]["name"] == "generate_ranked_recommendations"
        assert c.post("/api/drafts/c2/chat", json={"messages": [{"role": "assistant", "content": "x"}]}).status_code == 422


def test_import_picks(client):
    client.post("/api/drafts", json={"name": "imp", "user_slot": 2})
    r = client.post("/api/drafts/imp/import-picks", json={"format": "csv", "content": "pick_number,player_name\n1,Nikola Jokic\n2,Ghost\n"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 1 and body["skipped"][0]["reason"].startswith("unresolved")
    assert body["draft"]["clock"]["current_pick"] == 2
    assert client.post("/api/drafts/imp/import-picks", json={"format": "xml", "content": "x"}).status_code == 422
