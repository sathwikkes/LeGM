from legm.draft.persistence import list_drafts, load_draft, save_draft
from legm.draft.simulate import simulate
from legm.draft.state import available, make_pick, undo


def test_round_trip_and_undo(draft, tmp_path):
    s = simulate(draft, until_pick=10, seed=3)
    path = save_draft(s, tmp_path)
    assert path.name == "test.json"
    loaded = load_draft("test", tmp_path)
    assert loaded == s
    assert loaded.pool[available(loaded)[0].player_id].positions == available(s)[0].positions
    back = undo(loaded)
    assert len(back.picks) == 8
    nxt = make_pick(loaded, available(loaded)[0].player_id)
    assert len(nxt.picks) == 10
    assert list_drafts(tmp_path) == ["test"]
    assert list_drafts(tmp_path / "missing") == []
