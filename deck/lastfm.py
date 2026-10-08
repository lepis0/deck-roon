"""Last.fm: the listening history the weekly list is based on."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from .store import data_dir, now, read_cache, write_json

API = "https://ws.audioscrobbler.com/2.0/"
CACHE_MAX_AGE = 24 * 60 * 60
PAGE_SIZE = 1000
# Last.fm error codes worth retrying: operation failed, service offline,
# temporarily unavailable, rate limit.
TEMPORARY_ERRORS = {8, 11, 16, 29}


class LastFm:
    def __init__(self, key: str, user: str) -> None:
        self.key = key
        self.user = user
        self.http = httpx.Client(timeout=30)

    def _get(self, method: str, **params: str | int) -> dict:
        query = {"method": method, "user": self.user, "api_key": self.key, "format": "json", **params}
        for attempt in range(1, 4):
            try:
                r = self.http.get(API, params=query)
                body = r.json()
            except (httpx.HTTPError, ValueError) as e:
                if attempt == 3:
                    raise RuntimeError(f"Last.fm {method}: {e}") from e
            else:
                if "error" not in body:
                    return body
                if body["error"] not in TEMPORARY_ERRORS or attempt == 3:
                    raise RuntimeError(f"Last.fm {method}: {body.get('message')} ({body['error']})")
            time.sleep(2 * attempt)
        raise AssertionError("unreachable")

    def top_artists(self, period: str, limit: int) -> list[dict]:
        body = self._get("user.gettopartists", period=period, limit=limit)
        return [{"name": a["name"], "plays": int(a["playcount"])} for a in body["topartists"]["artist"]]

    def top_artists_since(self, start: int, limit: int) -> list[dict]:
        body = self._get("user.getweeklyartistchart", **{"from": start, "to": now()})
        artists = [{"name": a["name"], "plays": int(a["playcount"])}
                   for a in body["weeklyartistchart"]["artist"]]
        artists.sort(key=lambda a: -a["plays"])
        return artists[:limit]

    def _top_albums_page(self, period: str, limit: int, page: int) -> tuple[list[dict], int]:
        body = self._get("user.gettopalbums", period=period, limit=limit, page=page)
        top = body["topalbums"]
        pages = int(top.get("@attr", {}).get("totalPages", 1))
        albums = [{"artist": a["artist"]["name"], "album": a["name"], "plays": int(a["playcount"])}
                  for a in top["album"]]
        return albums, pages

    def top_albums(self, period: str, limit: int) -> list[dict]:
        return self._top_albums_page(period, limit, 1)[0]

    def listened_albums(self, min_plays: int) -> list[dict]:
        """Every album with at least `min_plays` plays, most played first. Cached for a day."""
        cache_path = albums_cache_path()
        cached = read_cache(cache_path, None)
        if (cached and cached.get("user") == self.user and cached.get("min_plays") == min_plays
                and now() - cached.get("fetched", 0) < CACHE_MAX_AGE):
            return cached["albums"]
        albums: list[dict] = []
        page = 1
        while True:
            items, pages = self._top_albums_page("overall", PAGE_SIZE, page)
            below = next((i for i, a in enumerate(items) if a["plays"] < min_plays), None)
            albums += items[:below]
            if below is not None or page >= pages:
                break
            page += 1
        write_json(cache_path, {"user": self.user, "min_plays": min_plays, "fetched": now(), "albums": albums})
        return albums


def albums_cache_path() -> Path:
    return data_dir() / "cache" / "lastfm-albums.json"
