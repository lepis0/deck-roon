"""The weekly list, everything suggested before, and the shelf."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .names import same_album
from .store import data_dir, now, read_json, write_json


def curated_path() -> Path:
    return data_dir() / "curated.json"


def history_path() -> Path:
    return data_dir() / "history.json"


def shelf_path() -> Path:
    return data_dir() / "shelf.json"


def current_round(at: int | None = None) -> str:
    """The ISO week, e.g. "2026-W41"."""
    year, week, _ = dt.date.fromtimestamp(at or now()).isocalendar()
    return f"{year}-W{week:02d}"


def round_label(round_id: str) -> str:
    year, week = round_id.split("-W")
    return f"viikko {int(week)}/{year}"


def load_curated() -> dict | None:
    return read_json(curated_path(), None)


def save_curated(curated: dict) -> None:
    write_json(curated_path(), curated)


def load_history() -> list[dict]:
    return read_json(history_path(), [])


def load_shelf() -> list[dict]:
    return read_json(shelf_path(), [])


def publish(albums: list[dict], at: int | None = None) -> dict:
    """Replaces the weekly list and adds its albums to the history."""
    at = at or now()
    round_id = current_round(at)
    curated = {"round": round_id, "created": at, "albums": albums}
    # Last week's TIDAL playlist, replaced by the next sync_playlist.
    previous = (load_curated() or {}).get("playlist_id")
    if previous:
        curated["previous_playlist_id"] = previous
    history = load_history()
    for a in albums:
        history.append({"id": a["id"], "artist": a["artist"], "album": a["album"], "year": a.get("year"),
                        "round": round_id, "rejected": False})
    write_json(history_path(), history)
    save_curated(curated)
    return curated


def _mark_history(album_id: str, **changes: object) -> None:
    history = load_history()
    for h in history:
        if h["id"] == album_id:
            h.update(changes)
    write_json(history_path(), history)


def reject(album_id: str) -> None:
    """"Not for me": off this week's list, and the next list avoids records like it."""
    curated = load_curated()
    if curated:
        curated["albums"] = [a for a in curated["albums"] if a["id"] != album_id]
        save_curated(curated)
    _mark_history(album_id, rejected=True)


def add_to_shelf(album: dict) -> None:
    shelf = load_shelf()
    if not any(s["id"] == album["id"] or same_album(s["artist"], s["album"], album["artist"], album["album"])
               for s in shelf):
        shelf.append({"id": album["id"], "artist": album["artist"], "album": album["album"],
                      "year": album.get("year"), "added": now()})
        write_json(shelf_path(), shelf)
    _mark_history(album["id"], rejected=False)


def remove_from_shelf(album_id: str) -> None:
    write_json(shelf_path(), [s for s in load_shelf() if s["id"] != album_id])


def find_album(album_id: str) -> dict | None:
    """An album of this week's list or of the history."""
    for a in (load_curated() or {}).get("albums", []):
        if a["id"] == album_id:
            return a
    for h in reversed(load_history()):
        if h["id"] == album_id:
            return h
    return None
