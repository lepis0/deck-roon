"""TIDAL API v2 (openapi.tidal.com): album search, the weekly playlist and favourites.

Searching needs only the app's own client credentials. The playlist and favourites
need the user's sign-in (authorization code with PKCE), saved in /data/tidal-token.json.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import Config
from .store import data_dir, now, read_cache, write_json

log = logging.getLogger(__name__)

API = "https://openapi.tidal.com/v2"
AUTHORIZE_URL = "https://login.tidal.com/authorize"
TOKEN_URL = "https://auth.tidal.com/v1/oauth2/token"
SCOPES = "collection.read collection.write playlists.read playlists.write search.read user.read"
JSON_API = "application/vnd.api+json"
# A short pause between calls keeps a run well under TIDAL's rate limits.
PAUSE = 0.25
# The longest Retry-After a call waits for before giving up.
MAX_WAIT = 60


class TidalError(Exception):
    pass


class NotSignedIn(TidalError):
    pass


@dataclass
class Album:
    id: str
    title: str
    artists: list[str]
    album_type: str
    year: int | None
    version: str = ""
    cover: str | None = None

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)

    @property
    def url(self) -> str:
        return f"https://tidal.com/album/{self.id}"


@dataclass
class _Token:
    access_token: str
    expires_at: int
    refresh_token: str = ""
    scope: str = ""
    user_id: str = ""


def _token_path() -> Path:
    return data_dir() / "tidal-token.json"


def _pkce_path() -> Path:
    return data_dir() / "cache" / "tidal-pkce.json"


class Tidal:
    def __init__(self, config: Config) -> None:
        config.require("tidal_client_id", "tidal_client_secret")
        self.config = config
        self.http = httpx.Client(timeout=30)
        self._app_token: _Token | None = None
        self._last_call = 0.0

    # ---- sign-in ---------------------------------------------------------

    def login_url(self) -> str:
        """Starts a sign-in: returns the TIDAL address to open in the browser."""
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        write_json(_pkce_path(), {"verifier": verifier, "state": state, "created": now()}, private=True)
        query = {
            "response_type": "code",
            "client_id": self.config.tidal_client_id,
            "redirect_uri": self.config.tidal_redirect_uri,
            "scope": SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def finish_login(self, redirected_url: str) -> None:
        """Finishes a sign-in from the address TIDAL redirected the browser to."""
        params = parse_qs(urlparse(redirected_url.strip()).query)
        if "error" in params:
            raise TidalError(f"TIDAL: {params['error'][0]} {params.get('error_description', [''])[0]}")
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        pending = read_cache(_pkce_path(), None)
        if not code:
            raise TidalError("Osoitteessa ei ole code-parametria")
        if not pending or pending["state"] != state:
            raise TidalError("Kirjautuminen vanhentui tai ei täsmää. Aloita alusta.")
        token = self._token_request({
            "grant_type": "authorization_code",
            "client_id": self.config.tidal_client_id,
            "code": code,
            "redirect_uri": self.config.tidal_redirect_uri,
            "code_verifier": pending["verifier"],
        })
        _pkce_path().unlink(missing_ok=True)
        self._save_user_token(token)

    def sign_out(self) -> None:
        _token_path().unlink(missing_ok=True)

    def _token_request(self, form: dict, basic: bool = False) -> dict:
        auth = (self.config.tidal_client_id, self.config.tidal_client_secret) if basic else None
        r = self.http.post(TOKEN_URL, data=form, auth=auth)
        if r.status_code != 200:
            raise TidalError(f"TIDAL-kirjautuminen epäonnistui ({r.status_code}): {r.text[:300]}")
        return r.json()

    def _save_user_token(self, body: dict, old: _Token | None = None) -> _Token:
        token = _Token(
            access_token=body["access_token"],
            expires_at=now() + int(body.get("expires_in", 3600)) - 60,
            refresh_token=body.get("refresh_token") or (old.refresh_token if old else ""),
            scope=body.get("scope", old.scope if old else ""),
            user_id=str(body.get("user_id") or (body.get("user") or {}).get("userId") or (old.user_id if old else "")),
        )
        write_json(_token_path(), asdict(token), private=True)
        return token

    def _user_token(self) -> str:
        saved = read_cache(_token_path(), None)
        if not saved:
            raise NotSignedIn("TIDAL-tunnusta ei ole kirjattu sisään")
        token = _Token(**saved)
        if token.expires_at > now():
            return token.access_token
        if not token.refresh_token:
            raise NotSignedIn("TIDAL-kirjautuminen vanheni, kirjaudu uudelleen")
        try:
            body = self._token_request({
                "grant_type": "refresh_token",
                "client_id": self.config.tidal_client_id,
                "refresh_token": token.refresh_token,
            })
        except TidalError as e:
            raise NotSignedIn(f"TIDAL-kirjautuminen vanheni, kirjaudu uudelleen ({e})") from e
        return self._save_user_token(body, token).access_token

    def _app_access_token(self) -> str:
        if self._app_token and self._app_token.expires_at > now():
            return self._app_token.access_token
        body = self._token_request({"grant_type": "client_credentials"}, basic=True)
        self._app_token = _Token(access_token=body["access_token"],
                                 expires_at=now() + int(body.get("expires_in", 3600)) - 60)
        return self._app_token.access_token

    # ---- HTTP ------------------------------------------------------------

    def _call(self, method: str, path: str, *, user: bool, params: dict | list | None = None,
              body: dict | None = None) -> dict:
        url = path if path.startswith("http") else API + path
        for attempt in range(1, 4):
            wait = PAUSE - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            token = self._user_token() if user else self._app_access_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": JSON_API}
            if body is not None:
                headers["Content-Type"] = JSON_API
            r = self.http.request(method, url, params=params, json=body, headers=headers)
            self._last_call = time.monotonic()
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", "5") or 5)
                if retry > MAX_WAIT or attempt == 3:
                    raise TidalError(f"TIDAL rajoittaa pyyntöjä, yritä uudelleen {retry} s päästä")
                log.warning("TIDAL 429, waiting %s s", retry)
                time.sleep(retry)
                continue
            if r.status_code == 401 and user:
                raise NotSignedIn("TIDAL hylkäsi kirjautumisen, kirjaudu uudelleen")
            if r.status_code >= 500 and attempt < 3:
                time.sleep(2 * attempt)
                continue
            if r.status_code >= 400:
                raise TidalError(f"TIDAL {method} {path}: {r.status_code} {r.text[:300]}")
            return r.json() if r.content else {}
        raise AssertionError("unreachable")

    def _pages(self, path: str, *, user: bool, params: dict, limit: int) -> list[dict]:
        """All `data` items of a paginated relationship, up to `limit`."""
        items: list[dict] = []
        doc = self._call("GET", path, user=user, params=params)
        while True:
            items += doc.get("data", [])
            nxt = doc.get("links", {}).get("next")
            if not nxt or len(items) >= limit:
                return items[:limit]
            doc = self._call("GET", nxt if nxt.startswith("http") else API + nxt, user=user)

    # ---- catalogue -------------------------------------------------------

    def search_albums(self, query: str, limit: int = 20) -> list[Album]:
        doc = self._call("GET", "/searchResults", user=False,
                         params={"filter[query]": query[:256], "countryCode": self.config.country,
                                 "include": "albums"})
        ids = [a["id"]
               for result in doc.get("data", [])
               for a in result.get("relationships", {}).get("albums", {}).get("data", [])
               if a.get("type") == "albums"][:limit]
        return self.albums(ids)

    def albums(self, ids: list[str]) -> list[Album]:
        """The albums with artists and cover, in the order of `ids`."""
        found: dict[str, Album] = {}
        for start in range(0, len(ids), 20):
            chunk = ids[start:start + 20]
            params = [("countryCode", self.config.country), ("include", "artists"), ("include", "coverArt")]
            params += [("filter[id]", i) for i in chunk]
            doc = self._call("GET", "/albums", user=False, params=params)
            for album in parse_albums(doc):
                found[album.id] = album
        return [found[i] for i in ids if i in found]

    def album_tracks(self, album_id: str) -> list[str]:
        items = self._pages(f"/albums/{album_id}/relationships/items", user=False,
                            params={"countryCode": self.config.country}, limit=500)
        return [i["id"] for i in items if i.get("type") == "tracks"]

    # ---- the user's TIDAL ------------------------------------------------

    def add_favorite_album(self, album_id: str) -> None:
        self._call("POST", "/userCollectionAlbums/me/relationships/items", user=True,
                   params={"countryCode": self.config.country},
                   body={"data": [{"id": album_id, "type": "albums"}]})

    def remove_favorite_album(self, album_id: str) -> None:
        self._call("DELETE", "/userCollectionAlbums/me/relationships/items", user=True,
                   body={"data": [{"id": album_id, "type": "albums"}]})

    def favorite_album_ids(self, limit: int = 3000) -> list[str]:
        items = self._pages("/userCollectionAlbums/me/relationships/items", user=True,
                            params={"countryCode": self.config.country}, limit=limit)
        return [i["id"] for i in items if i.get("type") == "albums"]

    def create_playlist(self, name: str, description: str) -> str:
        doc = self._call("POST", "/playlists", user=True, params={"countryCode": self.config.country},
                         body={"data": {"type": "playlists",
                                        "attributes": {"name": name, "accessType": "UNLISTED"}}})
        playlist_id = doc["data"]["id"]
        self._call("PATCH", f"/playlists/{playlist_id}", user=True,
                   body={"data": {"id": playlist_id, "type": "playlists",
                                  "attributes": {"description": description[:500]}}})
        return playlist_id

    def add_playlist_tracks(self, playlist_id: str, track_ids: list[str]) -> None:
        for start in range(0, len(track_ids), 50):
            chunk = track_ids[start:start + 50]
            self._call("POST", f"/playlists/{playlist_id}/relationships/items", user=True,
                       params={"countryCode": self.config.country},
                       body={"data": [{"id": t, "type": "tracks"} for t in chunk]})

    def delete_playlist(self, playlist_id: str) -> None:
        self._call("DELETE", f"/playlists/{playlist_id}", user=True)


def signed_in() -> bool:
    return _token_path().exists()


def parse_albums(doc: dict) -> list[Album]:
    """Albums from a JSON:API document with artists and coverArt included."""
    included = {(i["type"], i["id"]): i for i in doc.get("included", [])}
    albums = []
    for d in doc.get("data", []):
        if d.get("type") != "albums":
            continue
        attrs = d.get("attributes", {})
        rel = d.get("relationships", {})
        artists = [included[("artists", a["id"])]["attributes"]["name"]
                   for a in rel.get("artists", {}).get("data", []) if ("artists", a["id"]) in included]
        cover = None
        for art in rel.get("coverArt", {}).get("data", []):
            files = included.get(("artworks", art["id"]), {}).get("attributes", {}).get("files", [])
            # The smallest file at least 640 px wide, else the largest.
            files = sorted(files, key=lambda f: f.get("meta", {}).get("width", 0))
            pick = next((f for f in files if f.get("meta", {}).get("width", 0) >= 640), files[-1] if files else None)
            if pick:
                cover = pick["href"]
                break
        date = attrs.get("releaseDate") or ""
        albums.append(Album(
            id=d["id"],
            title=attrs.get("title", ""),
            artists=artists,
            album_type=attrs.get("albumType") or attrs.get("type") or "ALBUM",
            year=int(date[:4]) if date[:4].isdigit() else None,
            version=attrs.get("version") or "",
            cover=cover,
        ))
    return albums
