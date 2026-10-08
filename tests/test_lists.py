from deck import lists


def test_publish_reject_and_shelf(tmp_path, monkeypatch):
    monkeypatch.setenv("DECK_DATA", str(tmp_path))
    a = {"id": "1", "artist": "Gene Clark", "album": "No Other", "year": 1974, "reason": "x"}
    b = {"id": "2", "artist": "Big Star", "album": "#1 Record", "year": 1972, "reason": "y"}
    curated = lists.publish([a, b], at=1_791_000_000)
    assert curated["round"] == lists.current_round(1_791_000_000)
    assert len(lists.load_history()) == 2

    lists.reject("1")
    assert [x["id"] for x in lists.load_curated()["albums"]] == ["2"]
    assert lists.load_history()[0]["rejected"] is True

    lists.add_to_shelf(b)
    lists.add_to_shelf(b)
    assert [s["id"] for s in lists.load_shelf()] == ["2"]
    assert lists.find_album("1")["album"] == "No Other"  # from the history

    lists.save_curated({**lists.load_curated(), "playlist_id": "p1"})
    assert lists.publish([a])["previous_playlist_id"] == "p1"


def test_round_label():
    assert lists.round_label("2026-W41") == "viikko 41/2026"
