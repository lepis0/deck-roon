from deck.names import normalize, plain_artist, same_album


def test_normalize_rules():
    assert normalize("OK Computer") == "ok computer"
    assert normalize("Abbey Road (Remastered 2009)") == "abbey road"
    assert normalize("Pet Sounds [Deluxe Edition]") == "pet sounds"
    assert normalize("Sgt. Pepper's Lonely Hearts Club Band") == "sgt peppers lonely hearts club band"
    assert normalize("Hüsker Dü") == "husker du"
    assert normalize("Simon & Garfunkel") == "simon and garfunkel"
    assert normalize("AC/DC") == normalize("AC DC")
    assert normalize("Älymystö") == "alymysto"
    assert normalize("(What's the Story)") == "whats the story"
    assert normalize("Hunky Dory - 2015 Remaster") == "hunky dory"
    # A dash that is part of the title stays.
    assert normalize("Sign o' the Times - Live") == "sign o the times live"


def test_same_album():
    assert same_album("Radiohead", "OK Computer", "radiohead", "OK Computer (Collector's Edition)")
    assert not same_album("Radiohead", "Kid A", "Radiohead", "Amnesiac")


def test_plain_artist():
    assert plain_artist("[[3388026|Gene Clark]]") == "Gene Clark"
    assert plain_artist("[[1|Crosby, Stills & Nash]] / [[2|Neil Young]]") == "Crosby, Stills & Nash / Neil Young"
    assert plain_artist(None) == ""
