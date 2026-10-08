"""Roon: zones, and playing an album of the list through Roon's own search.

The Roon extension API cannot play by TIDAL id or add to playlists, so an album is
found the way a person would: search → Albums → the album → Play Album → action.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from roonapi import RoonApi, RoonDiscovery

from .config import Config
from .names import normalize, plain_artist
from .store import data_dir

log = logging.getLogger(__name__)

APPINFO = {
    "extension_id": "deck_roon_curated",
    "display_name": "Deck – viikon levyt",
    "display_version": "0.1.0",
    "publisher": "self-hosted",
    "email": "noreply@example.com",
    "website": "https://github.com/jarilehtinen/deck",
}

# Roon's action names, and their place in the action list if the names differ.
ACTIONS = {"play": ("Play Now", 0), "next": ("Add Next", 1), "queue": ("Queue", 2), "radio": ("Start Radio", 3)}
SESSION = "deck"


class RoonError(Exception):
    pass


class Roon:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.api: RoonApi | None = None
        self.status = "yhdistetään"
        self._lock = threading.Lock()

    # ---- connection -------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._connect_loop, name="roon", daemon=True).start()

    def _connect_loop(self) -> None:
        token_file = data_dir() / "roon-token.txt"
        while self.api is None:
            for host, port in self._cores():
                token = token_file.read_text().strip() if token_file.exists() else None
                self.status = (f"odotetaan hyväksyntää: Roon → Asetukset → Laajennukset → "
                               f"{APPINFO['display_name']} → Ota käyttöön") if not token else "yhdistetään"
                try:
                    api = RoonApi(APPINFO, token, host, port, blocking_init=True)
                except Exception as e:  # roonapi raises plain exceptions
                    log.warning("Roon %s:%s: %s", host, port, e)
                    self.status = f"ei yhteyttä Roon Coreen ({host}:{port})"
                    continue
                if api.token:
                    token_file.write_text(api.token)
                self.api = api
                self.status = "yhdistetty"
                log.info("connected to Roon Core at %s:%s", host, port)
                return
            time.sleep(15)

    def _cores(self) -> list[tuple[str, int]]:
        if self.config.roon_host:
            return [(self.config.roon_host, self.config.roon_port)]
        try:
            discovery = RoonDiscovery(None)
            try:
                return list(discovery.all() or [])
            finally:
                discovery.stop()
        except OSError as e:
            self.status = f"Roon Corea ei löytynyt lähiverkosta ({e}); aseta roon_host"
            return []

    @property
    def connected(self) -> bool:
        return self.api is not None

    def zones(self) -> list[dict]:
        if not self.api:
            return []
        zones = []
        for zone_id, z in (self.api.zones or {}).items():
            playing = (z.get("now_playing") or {}).get("three_line") or {}
            zones.append({"id": zone_id, "name": z.get("display_name", zone_id), "state": z.get("state"),
                          "now_playing": " – ".join(v for v in (playing.get("line2"), playing.get("line1")) if v)})
        return sorted(zones, key=lambda z: z["name"].lower())

    # ---- playing an album -------------------------------------------------

    def play_album(self, zone_id: str, artist: str, album: str, action: str) -> str:
        if not self.api:
            raise RoonError(f"Roon: {self.status}")
        if action not in ACTIONS:
            raise RoonError(f"tuntematon toiminto {action}")
        with self._lock:
            return self._play(zone_id, artist, album, action)

    def _browse(self, zone_id: str, **opts: Any) -> dict:
        result = self.api.browse_browse({"hierarchy": "search", "multi_session_key": SESSION,
                                         "zone_or_output_id": zone_id, **opts})
        if not result or result.get("action") == "message" and result.get("is_error"):
            raise RoonError(f"Roon: {(result or {}).get('message') or 'ei vastausta'}")
        return result

    def _load(self, count: int = 100) -> list[dict]:
        result = self.api.browse_load({"hierarchy": "search", "multi_session_key": SESSION,
                                       "offset": 0, "count": count})
        return (result or {}).get("items") or []

    def _play(self, zone_id: str, artist: str, album: str, action: str) -> str:
        self._browse(zone_id, pop_all=True, input=f"{artist} {album}")
        top = self._load()
        albums_list = next((i for i in top if i.get("title") == "Albums" and i.get("hint") == "list"), None)
        candidates: list[dict] = []
        if albums_list:
            self._browse(zone_id, item_key=albums_list["item_key"])
            candidates = self._load()
        item = best_match(candidates, artist, album)
        if not item:
            # The top hit is sometimes the album when the Albums list is not.
            item = best_match([i for i in top if i.get("title") not in ("Albums", "Artists", "Tracks")],
                              artist, album)
            if item:
                self._browse(zone_id, pop_all=True, input=f"{artist} {album}")
        if not item:
            raise RoonError(f"Roonin haku ei löytänyt albumia {artist} – {album}")

        # Open the album until its "Play Album" row shows (Roon may add a level for
        # the album's versions).
        self._browse(zone_id, item_key=item["item_key"])
        for _ in range(3):
            rows = self._load(5)
            if not rows:
                raise RoonError("Roon palautti tyhjän albumin")
            play_row = next((r for r in rows if r.get("title") == "Play Album"), None)
            if play_row is None and rows[0].get("hint") == "action_list":
                play_row = rows[0]
            if play_row:
                break
            if len(rows) == 1 and rows[0].get("hint") == "list":
                self._browse(zone_id, item_key=rows[0]["item_key"])
                continue
            raise RoonError("albumin soittotoimintoa ei löytynyt")
        else:
            raise RoonError("albumin soittotoimintoa ei löytynyt")

        self._browse(zone_id, item_key=play_row["item_key"])
        actions = self._load(10)
        name, index = ACTIONS[action]
        chosen = next((a for a in actions if a.get("title") == name), None)
        if chosen is None and len(actions) > index:
            chosen = actions[index]
        if chosen is None:
            raise RoonError(f"Roon ei tarjonnut toimintoa {name}")
        self._browse(zone_id, item_key=chosen["item_key"])
        return f"{item.get('title')} – {plain_artist(item.get('subtitle'))}"


def best_match(items: list[dict], artist: str, album: str) -> dict | None:
    """The browse row of the album: the title must match when normalised, and the
    artist must be one of the row's artists. Of several, the plain title first."""
    want_title, want_artist = normalize(album), normalize(artist)
    matches = []
    for i in items:
        if normalize(i.get("title") or "") != want_title:
            continue
        artists = normalize(plain_artist(i.get("subtitle")))
        if want_artist and want_artist not in artists:
            continue
        matches.append(i)
    if not matches:
        return None
    return min(matches, key=lambda i: ("(" in (i.get("title") or ""), len(i.get("title") or "")))
