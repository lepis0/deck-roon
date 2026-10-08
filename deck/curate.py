"""`deck taste` and `deck curate submit`, used by the weekly run (curate/prompt.md)."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from . import lists
from .config import Config
from .lastfm import LastFm
from .names import normalize, same_album
from .store import data_dir, now, read_cache, write_json
from .tidal import Album, NotSignedIn, Tidal, TidalError

log = logging.getLogger(__name__)

MAX_ALBUMS = 20
LISTENED_MIN_PLAYS = 3
THREE_YEARS = 3 * 365 * 24 * 60 * 60
# TIDAL searches a day by `deck curate submit`.
SEARCH_BUDGET = 100
SEARCH_MAX_AGE = 24 * 60 * 60
NOT_FOUND_MAX_AGE = 182 * 24 * 60 * 60
FAVORITES_MAX_AGE = 24 * 60 * 60


# ---- checking candidates ----------------------------------------------------

def pick(artist: str, album: str, found: list[Album]) -> Album | None:
    """The candidate's album among the search hits: artist and title must match when
    normalised. Of several, an album before an EP or single, then the plain title
    before editions, then the oldest."""
    want_artist, want_title = normalize(artist), normalize(album)
    matches = [f for f in found
               if normalize(f.title) == want_title and any(normalize(a) == want_artist for a in f.artists)]
    if not matches:
        return None
    return min(matches, key=lambda f: (f.album_type != "ALBUM", bool(f.version) or "(" in f.title or "[" in f.title,
                                       f.year or 9999))


def known(c: dict, shelf: list[dict], history: list[dict], listened: list[dict]) -> str | None:
    """A rejection by the candidate's own names alone, so it need not be searched."""
    def same(artist: str, name: str) -> bool:
        return same_album(artist, name, c["artist"], c["album"])

    if any(same(s["artist"], s["album"]) for s in shelf):
        return "on_shelf"
    if any(same(h["artist"], h["album"]) for h in history):
        return "suggested_before"
    if any(x["plays"] >= LISTENED_MIN_PLAYS and same(x["artist"], x["album"]) for x in listened):
        return "listened"
    return None


def check(candidates: list[dict], hits: list[list[Album] | None], shelf: list[dict], history: list[dict],
          listened: list[dict], favorites: set[str]) -> tuple[dict, list[dict]]:
    """Checks the candidates. `hits[i]` holds the TIDAL hits for candidates[i], None
    when it was not searched. Returns the report and the albums for the list."""
    passed: list[dict] = []
    rejected: list[dict] = []
    for c, found in zip(candidates, hits, strict=True):
        def reject(reason: str, album: Album | None = None) -> None:
            r = {"artist": c["artist"], "album": c["album"], "reason": reason}
            if album:
                r["tidal_id"] = album.id
            rejected.append(r)

        reason = known(c, shelf, history, listened)
        if reason:
            reject(reason)
            continue
        if found is None:
            reject("not_checked")
            continue
        album = pick(c["artist"], c["album"], found)
        if not album:
            reject("not_found")
            continue

        def same(artist: str, name: str) -> bool:
            return same_album(artist, name, album.artist, album.title) or any(
                same_album(artist, name, a, album.title) for a in album.artists)

        if album.id in favorites or any(s["id"] == album.id or same(s["artist"], s["album"]) for s in shelf):
            reject("on_shelf", album)
        elif any(h["id"] == album.id or same(h["artist"], h["album"]) for h in history):
            reject("suggested_before", album)
        elif any(x["plays"] >= LISTENED_MIN_PLAYS and same(x["artist"], x["album"]) for x in listened):
            reject("listened", album)
        elif any(p["id"] == album.id or same(p["artist"], p["album"]) for p in passed):
            reject("duplicate", album)
        else:
            passed.append({"id": album.id, "artist": album.artist, "artists": album.artists,
                           # The original year: TIDAL's release date is often a reissue's.
                           "album": album.title, "year": _year(c.get("year")) or album.year,
                           "cover": album.cover, "url": album.url, "reason": c.get("reason", "").strip()})

    unused = passed[MAX_ALBUMS:]
    passed = passed[:MAX_ALBUMS]

    def brief(albums: list[dict]) -> list[dict]:
        return [{"artist": a["artist"], "album": a["album"], "year": a["year"], "tidal_id": a["id"]} for a in albums]

    report = {"accepted": brief(passed), "rejected": rejected, "missing": MAX_ALBUMS - len(passed)}
    if unused:
        report["unused"] = brief(unused)
    return report, passed


def _year(value: object) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


# ---- the search cache -------------------------------------------------------

def _search_cache_path() -> Path:
    return data_dir() / "cache" / "curate-searches.json"


class SearchCache:
    """TIDAL searches of the last day, the day's search count, and candidates that
    were not on TIDAL (kept for half a year)."""

    def __init__(self) -> None:
        raw = read_cache(_search_cache_path(), {})
        t = now()
        self.searches: dict[str, dict] = {k: v for k, v in raw.get("searches", {}).items()
                                          if t - v["at"] < SEARCH_MAX_AGE}
        self.not_found: list[dict] = [n for n in raw.get("not_found", []) if t - n["at"] < NOT_FOUND_MAX_AGE]

    @staticmethod
    def key(artist: str, album: str) -> str:
        return f"{normalize(artist)}\t{normalize(album)}"

    def searches_left(self) -> int:
        return max(0, SEARCH_BUDGET - len(self.searches))

    def get(self, artist: str, album: str) -> list[Album] | None:
        hit = self.searches.get(self.key(artist, album))
        return [Album(**a) for a in hit["hits"]] if hit else None

    def is_not_found(self, artist: str, album: str) -> bool:
        return any(same_album(n["artist"], n["album"], artist, album) for n in self.not_found)

    def add(self, artist: str, album: str, hits: list[Album]) -> None:
        self.searches[self.key(artist, album)] = {"at": now(), "hits": [asdict(h) for h in hits]}

    def remember_not_found(self, artist: str, album: str) -> None:
        if not self.is_not_found(artist, album):
            self.not_found.append({"artist": artist, "album": album, "at": now()})

    def save(self) -> None:
        write_json(_search_cache_path(), {"searches": self.searches, "not_found": self.not_found})


# ---- TIDAL favourites -------------------------------------------------------

def _favorites_cache_path() -> Path:
    return data_dir() / "cache" / "tidal-favorites.json"


def favorite_ids(tidal: Tidal) -> list[str]:
    """The user's TIDAL album favourites in TIDAL's order (cached for a day), empty
    when not signed in."""
    cached = read_cache(_favorites_cache_path(), None)
    if cached and now() - cached["fetched"] < FAVORITES_MAX_AGE:
        return cached["ids"]
    try:
        ids = tidal.favorite_album_ids()
    except (NotSignedIn, TidalError) as e:
        log.warning("cannot read TIDAL favourites: %s", e)
        return cached["ids"] if cached else []
    write_json(_favorites_cache_path(), {"fetched": now(), "ids": ids})
    return ids


def forget_favorites_cache() -> None:
    _favorites_cache_path().unlink(missing_ok=True)


# ---- commands ---------------------------------------------------------------

def _lastfm(config: Config) -> LastFm:
    config.require("lastfm_api_key", "lastfm_user")
    return LastFm(config.lastfm_api_key, config.lastfm_user)


def taste() -> None:
    """`deck taste`: prints the taste profile as JSON."""
    config = Config.load()
    lastfm = _lastfm(config)
    tidal = Tidal(config)
    shelf = lists.load_shelf()
    history = lists.load_history()
    shelf_ids = {s["id"] for s in shelf}

    favorites: list[str] = []
    try:
        # Names for the first 100 only: each 20 albums cost a TIDAL call.
        favorites = [f"{a.artist} – {a.title}" for a in tidal.albums(favorite_ids(tidal)[:100])]
    except (NotSignedIn, TidalError) as e:
        log.warning("TIDAL favourites left out: %s", e)

    profile = {
        "lastfm": {
            "user": config.lastfm_user,
            "top_artists": {
                "overall": lastfm.top_artists("overall", 200),
                "3year": lastfm.top_artists_since(now() - THREE_YEARS, 100),
                "12month": lastfm.top_artists("12month", 100),
            },
            "top_albums": lastfm.top_albums("overall", 200),
            "listened": [f"{a['artist']} – {a['album']}" for a in lastfm.listened_albums(LISTENED_MIN_PLAYS)],
        },
        "shelf": [{"artist": s["artist"], "album": s["album"], "year": s.get("year")} for s in shelf],
        "tidal_favorites": favorites,
        "not_on_tidal": [f"{n['artist']} – {n['album']}" for n in SearchCache().not_found],
        "history": [{"artist": h["artist"], "album": h["album"], "round": h["round"],
                     "rejected": h.get("rejected", False), "on_shelf": h["id"] in shelf_ids}
                    for h in history],
    }
    # One value per line, so that Claude can read the profile in parts.
    json.dump(profile, sys.stdout, ensure_ascii=False, indent=1)
    print()


def submit(dry_run: bool) -> None:
    """`deck curate submit [--dry-run]`: candidates from stdin, report to stdout."""
    try:
        candidates = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Ehdokkaat eivät ole kelvollista JSONia: {e}")
    if not isinstance(candidates, list) or not all(
            isinstance(c, dict) and c.get("artist") and c.get("album") for c in candidates):
        raise SystemExit('Odotin listaa: [{"artist": "…", "album": "…", "reason": "…"}]')

    config = Config.load()
    tidal = Tidal(config)
    shelf = lists.load_shelf()
    history = lists.load_history()
    listened = _lastfm(config).listened_albums(LISTENED_MIN_PLAYS)
    favorites = set(favorite_ids(tidal))
    cache = SearchCache()

    searched = 0
    hits: list[list[Album] | None] = []
    for c in candidates:
        if known(c, shelf, history, listened) or cache.is_not_found(c["artist"], c["album"]):
            hits.append([] if cache.is_not_found(c["artist"], c["album"]) else None)
            continue
        cached = cache.get(c["artist"], c["album"])
        if cached is not None:
            hits.append(cached)
            continue
        if cache.searches_left() == 0:
            hits.append(None)
            continue
        try:
            found = tidal.search_albums(f"{c['artist']} {c['album']}")
        except TidalError as e:
            cache.save()
            raise SystemExit(f"TIDAL-haku epäonnistui ({c['artist']} – {c['album']}): {e}")
        searched += 1
        cache.add(c["artist"], c["album"], found)
        if not pick(c["artist"], c["album"], found):
            cache.remember_not_found(c["artist"], c["album"])
        hits.append(found)
    cache.save()

    report, albums = check(candidates, hits, shelf, history, listened, favorites)
    report["searched"] = searched
    report["searches_left"] = cache.searches_left()

    if not dry_run:
        if not albums:
            raise SystemExit("Yhtään albumia ei hyväksytty, joten listaa ei kirjoitettu")
        lists.publish(albums)
        report["written"] = len(albums)
        report["playlist"] = sync_playlist(config, tidal)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
    print()


def sync_playlist(config: Config, tidal: Tidal | None = None) -> str:
    """Creates this week's TIDAL playlist from the list (and removes last week's,
    unless tidal_keep_playlists). Returns a short status for the report or the UI."""
    tidal = tidal or Tidal(config)
    curated = lists.load_curated()
    if not curated or not curated["albums"]:
        return "ei listaa"
    try:
        tracks: list[str] = []
        for a in curated["albums"]:
            tracks += tidal.album_tracks(a["id"])
        name = f"Deck · {lists.round_label(curated['round'])}"
        description = "Viikon levysuositukset: " + "; ".join(f"{a['artist']} – {a['album']}"
                                                             for a in curated["albums"])
        playlist_id = tidal.create_playlist(name, description)
        tidal.add_playlist_tracks(playlist_id, tracks)
    except NotSignedIn as e:
        return f"ohitettu: {e}"
    except TidalError as e:
        return f"virhe: {e}"

    previous = curated.get("playlist_id") or curated.get("previous_playlist_id")
    curated = lists.load_curated() or curated
    curated["playlist_id"] = playlist_id
    curated.pop("previous_playlist_id", None)
    lists.save_curated(curated)
    if previous and previous != playlist_id and not config.tidal_keep_playlists:
        try:
            tidal.delete_playlist(previous)
        except TidalError as e:
            log.warning("cannot delete the previous playlist %s: %s", previous, e)
    return f"luotu: {name}, {len(tracks)} kappaletta"
