"""The web page: this week's list with reasons, played in Roon."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import lists
from .config import Config, ConfigError
from .curate import forget_favorites_cache, sync_playlist
from .roon import Roon, RoonError
from .store import BrokenFile
from .tidal import NotSignedIn, Tidal, TidalError, signed_in

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"

config = Config.load()
roon = Roon(config)


@asynccontextmanager
async def lifespan(_: FastAPI):
    roon.start()
    yield


app = FastAPI(title="Deck", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def tidal() -> Tidal:
    return Tidal(config)


async def run(fn, *args):
    """Runs blocking IO (Roon, TIDAL, files) off the event loop."""
    return await asyncio.get_running_loop().run_in_executor(None, partial(fn, *args))


@app.exception_handler(BrokenFile)
@app.exception_handler(ConfigError)
async def user_error(_: Request, e: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=500)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    """Lets a phone add the page to its home screen as an app."""
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/api/state")
def state() -> dict:
    shelf = lists.load_shelf()
    return {
        "curated": lists.load_curated(),
        "round_label": lists.round_label((lists.load_curated() or {}).get("round", "2000-W01")),
        "shelf": [s["id"] for s in shelf],
        "tidal": {"signed_in": signed_in()},
        "roon": {"connected": roon.connected, "status": roon.status, "zones": roon.zones()},
    }


@app.get("/api/history")
def history() -> dict:
    rounds: dict[str, list[dict]] = {}
    for h in lists.load_history():
        rounds.setdefault(h["round"], []).append(h)
    shelf = lists.load_shelf()
    shelf_ids = {s["id"] for s in shelf}
    return {"rounds": [{"round": r, "label": lists.round_label(r),
                        "albums": [{**a, "on_shelf": a["id"] in shelf_ids} for a in albums]}
                       for r, albums in sorted(rounds.items(), reverse=True)],
            "shelf": sorted(shelf, key=lambda s: -s.get("added", 0))}


class PlayRequest(BaseModel):
    zone_id: str
    album_id: str
    action: str = "play"


@app.post("/api/play")
async def play(req: PlayRequest) -> dict:
    album = lists.find_album(req.album_id)
    if not album:
        raise HTTPException(404, "Albumia ei ole listalla")
    artist = (album.get("artists") or [album["artist"]])[0]
    try:
        played = await run(roon.play_album, req.zone_id, artist, album["album"], req.action)
    except RoonError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "message": played}


class AlbumRequest(BaseModel):
    album_id: str


@app.post("/api/shelf")
async def add_to_shelf(req: AlbumRequest) -> dict:
    """Hyllyyn: a TIDAL favourite (so it shows in Roon's library) and a liked record."""
    album = lists.find_album(req.album_id)
    if not album:
        raise HTTPException(404, "Albumia ei ole listalla")
    note = "lisätty TIDAL-suosikkeihin"
    try:
        await run(tidal().add_favorite_album, album["id"])
        forget_favorites_cache()
    except NotSignedIn:
        note = "tallennettu vain Deckiin: kirjaudu TIDALiin, niin albumi menee myös suosikkeihin"
    except TidalError as e:
        raise HTTPException(502, str(e))
    await run(lists.add_to_shelf, album)
    return {"ok": True, "message": note}


@app.delete("/api/shelf/{album_id}")
async def remove_from_shelf(album_id: str) -> dict:
    try:
        await run(tidal().remove_favorite_album, album_id)
        forget_favorites_cache()
    except NotSignedIn:
        pass
    except TidalError as e:
        raise HTTPException(502, str(e))
    await run(lists.remove_from_shelf, album_id)
    return {"ok": True}


@app.post("/api/reject")
async def reject(req: AlbumRequest) -> dict:
    await run(lists.reject, req.album_id)
    return {"ok": True}


@app.post("/api/playlist")
async def playlist() -> dict:
    status = await run(sync_playlist, config)
    if not status.startswith("luotu"):
        raise HTTPException(502, status)
    return {"ok": True, "message": status}


@app.get("/tidal/login")
def tidal_login() -> RedirectResponse:
    return RedirectResponse(tidal().login_url())


@app.get("/tidal/callback")
async def tidal_callback(request: Request) -> RedirectResponse:
    try:
        await run(tidal().finish_login, str(request.url))
    except TidalError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse("/")


class FinishRequest(BaseModel):
    url: str


@app.post("/api/tidal/finish")
async def tidal_finish(req: FinishRequest) -> dict:
    """For when the redirect address does not reach this server: the user pastes it."""
    try:
        await run(tidal().finish_login, req.url)
    except TidalError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/tidal/logout")
def tidal_logout() -> dict:
    tidal().sign_out()
    return {"ok": True}
