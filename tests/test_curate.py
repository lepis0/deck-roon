from deck.curate import check, pick
from deck.tidal import Album, parse_albums


def album(id, artist, title, year=1974, album_type="ALBUM", version=""):
    return Album(id=id, title=title, artists=[artist], album_type=album_type, year=year, version=version)


def cand(artist, album_name, reason="syy"):
    return {"artist": artist, "album": album_name, "reason": reason}


def run(candidates, hits, shelf=(), history=(), listened=(), favorites=()):
    return check(candidates, hits, list(shelf), list(history), list(listened), set(favorites))


def reasons(report):
    return [r["reason"] for r in report["rejected"]]


def test_accepts_matching_album_with_reason():
    report, albums = run([cand("Gene Clark", "No Other", "Kosmista kantria.")],
                         [[album("1", "Gene Clark", "No Other (2019 Remaster)")]])
    assert report["missing"] == 19
    assert albums[0]["id"] == "1" and albums[0]["reason"] == "Kosmista kantria."
    assert albums[0]["url"] == "https://tidal.com/album/1"


def test_candidate_year_wins_over_reissue_date():
    _, albums = run([{**cand("Convulse", "World Without God"), "year": 1991}],
                    [[album("1", "Convulse", "World Without God (2026 Remaster)", 2010)]])
    assert albums[0]["year"] == 1991
    _, albums = run([{**cand("Convulse", "World Without God"), "year": "?"}],
                    [[album("1", "Convulse", "World Without God", 2010)]])
    assert albums[0]["year"] == 2010


def test_not_found_when_no_hit_matches():
    report, _ = run([cand("Gene Clark", "No Other")], [[album("1", "Gene Simmons", "No Other Guy")]])
    assert reasons(report) == ["not_found"]


def test_known_by_name_needs_no_search():
    shelf = [{"id": "9", "artist": "Big Star", "album": "#1 Record"}]
    history = [{"id": "8", "artist": "Judee Sill", "album": "Heart Food"}]
    listened = [{"artist": "Nirvana", "album": "Nevermind", "plays": 3},
                {"artist": "Wipers", "album": "Youth of America", "plays": 2}]
    report, albums = run(
        [cand("Big Star", "#1 Record"), cand("Judee Sill", "Heart Food"), cand("Nirvana", "Nevermind"),
         cand("Wipers", "Youth of America")],
        [None, None, None, [album("5", "Wipers", "Youth of America")]],
        shelf, history, listened)
    assert reasons(report) == ["on_shelf", "suggested_before", "listened"]
    assert [a["id"] for a in albums] == ["5"]


def test_tidal_favourite_counts_as_shelf():
    report, _ = run([cand("Gene Clark", "No Other")], [[album("1", "Gene Clark", "No Other")]], favorites={"1"})
    assert reasons(report) == ["on_shelf"]
    assert report["rejected"][0]["tidal_id"] == "1"


def test_duplicate_and_not_checked():
    hit = [album("1", "Gene Clark", "No Other")]
    report, _ = run([cand("Gene Clark", "No Other"), cand("Gene Clark", "No Other (Deluxe)"), cand("X", "Y")],
                    [hit, hit, None])
    assert reasons(report) == ["duplicate", "not_checked"]


def test_pick_prefers_original_album():
    found = [album("3", "Big Star", "#1 Record", 2009, version="Remastered"),
             album("2", "Big Star", "#1 Record", 1972, album_type="EP"),
             album("1", "Big Star", "#1 Record", 1972),
             album("4", "Big Star", "#1 Record (Deluxe)", 1972)]
    assert pick("Big Star", "#1 Record", found).id == "1"


def test_caps_at_twenty_and_keeps_spares():
    candidates = [cand(f"Artist {i}", f"Album {i}") for i in range(23)]
    hits = [[album(str(i), f"Artist {i}", f"Album {i}")] for i in range(23)]
    report, albums = run(candidates, hits)
    assert len(albums) == 20 and report["missing"] == 0
    assert [u["tidal_id"] for u in report["unused"]] == ["20", "21", "22"]


def test_parse_albums_reads_artists_and_cover():
    doc = {
        "data": [{"id": "1", "type": "albums",
                  "attributes": {"title": "No Other", "albumType": "ALBUM", "releaseDate": "1974-09-01"},
                  "relationships": {"artists": {"data": [{"id": "a", "type": "artists"}]},
                                    "coverArt": {"data": [{"id": "c", "type": "artworks"}]}}}],
        "included": [
            {"id": "a", "type": "artists", "attributes": {"name": "Gene Clark"}},
            {"id": "c", "type": "artworks", "attributes": {"files": [
                {"href": "https://img/1280.jpg", "meta": {"width": 1280, "height": 1280}},
                {"href": "https://img/160.jpg", "meta": {"width": 160, "height": 160}},
                {"href": "https://img/640.jpg", "meta": {"width": 640, "height": 640}}]}},
        ],
    }
    [a] = parse_albums(doc)
    assert (a.title, a.artists, a.year, a.cover) == ("No Other", ["Gene Clark"], 1974, "https://img/640.jpg")
