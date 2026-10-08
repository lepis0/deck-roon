from deck.roon import best_match


def test_best_match_prefers_plain_title_by_the_artist():
    items = [
        {"title": "No Other (Deluxe Edition)", "subtitle": "[[3388026|Gene Clark]]", "item_key": "a"},
        {"title": "No Other Guy", "subtitle": "[[20681082|Gene Simmons]]", "item_key": "b"},
        {"title": "No Other", "subtitle": "[[3388026|Gene Clark]]", "item_key": "c"},
        {"title": "No Other", "subtitle": "[[1|Someone Else]]", "item_key": "d"},
    ]
    assert best_match(items, "Gene Clark", "No Other")["item_key"] == "c"
    assert best_match(items[:2], "Gene Clark", "No Other")["item_key"] == "a"
    assert best_match(items[1:2], "Gene Clark", "No Other") is None
