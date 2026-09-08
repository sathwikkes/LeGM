import json

from legm.draft.state import available, current_pick
from legm.integrations import ExternalPick, FileSource, ManualSource, YahooSource, apply_external_picks, parse_picks_text
from legm.integrations.yahoo import parse_draft_results, parse_player_names


def test_apply_external_picks_in_order(draft):
    a = available(draft)
    picks = [
        ExternalPick(1, a[0].name),
        ExternalPick(2, a[1].name.upper()),  # name normalization
        ExternalPick(4, a[3].name),  # out of order: pick 3 missing
        ExternalPick(3, "Nobody Real"),
    ]
    state, report = apply_external_picks(draft, picks)
    assert report.applied_count == 2 and current_pick(state) == 3
    reasons = [r for _, r in report.skipped]
    assert any("unresolved" in r for r in reasons) and any("out of order" in r for r in reasons)
    # Re-applying already-known picks is a no-op; a conflicting one is reported.
    state2, report2 = apply_external_picks(state, [ExternalPick(1, a[0].name), ExternalPick(2, a[5].name)])
    assert report2.applied_count == 0 and state2.picks == state.picks
    assert "conflict" in report2.skipped[0][1]


def test_parse_csv_and_json_and_file(tmp_path):
    csv_text = "pick_number,player_name,team_name\n1,Player 000,Team 1\n2,Player 001,\n"
    assert [p.player_name for p in parse_picks_text(csv_text, "csv")] == ["Player 000", "Player 001"]
    js = json.dumps({"picks": [{"pick_number": 1, "player": "Player 000", "nba_id": 1000}]})
    p = parse_picks_text(js, "json")[0]
    assert p.player_id == 1000 and p.source == "file"
    f = tmp_path / "picks.csv"
    f.write_text(csv_text)
    assert len(FileSource(f).poll()) == 2
    assert FileSource(tmp_path / "missing.csv").poll() == []
    m = ManualSource([ExternalPick(1, "x")])
    m.add(ExternalPick(2, "y"))
    assert [p.pick_number for p in m.poll()] == [1, 2]


YAHOO_DRAFT = {"fantasy_content": {"league": [{"league_key": "l.1"}, {"draft_results": {
    "0": {"draft_result": {"pick": 1, "round": 1, "team_key": "t.1", "player_key": "p.100"}},
    "1": {"draft_result": {"pick": 2, "round": 1, "team_key": "t.2", "player_key": "p.200"}},
    "count": 2}}]}}
YAHOO_PLAYERS = {"fantasy_content": {"league": [{"league_key": "l.1"}, {"players": {
    "0": {"player": [[{"player_key": "p.100"}, {"name": {"full": "Player 000"}}]]},
    "1": {"player": [[{"player_key": "p.200"}, {"name": {"full": "Player 001"}}]]},
    "count": 2}}]}}


def test_yahoo_parsing_and_source(draft):
    assert [r["player_key"] for r in parse_draft_results(YAHOO_DRAFT)] == ["p.100", "p.200"]
    assert parse_player_names(YAHOO_PLAYERS) == {"p.100": "Player 000", "p.200": "Player 001"}
    assert parse_draft_results({}) == [] and parse_player_names({"x": 1}) == {}
    calls = []

    def fetch(url, token):
        calls.append((url, token))
        return YAHOO_DRAFT if "draftresults" in url else YAHOO_PLAYERS

    picks = YahooSource("l.1", "tok", fetch=fetch).poll()
    assert [(p.pick_number, p.player_name, p.source) for p in picks] == [(1, "Player 000", "yahoo"), (2, "Player 001", "yahoo")]
    assert calls[0][1] == "tok" and "player_keys=p.100,p.200" in calls[1][0]
    state, report = apply_external_picks(draft, picks)
    assert report.applied_count == 2
