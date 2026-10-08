"""Atomic JSON files and the data directory."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    path = Path(os.environ.get("DECK_DATA", "/data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def now() -> int:
    return int(time.time())


class BrokenFile(Exception):
    """A user file that cannot be parsed. It is never overwritten."""


def read_json(path: Path, default: Any) -> Any:
    """Reads a JSON file. A missing file is `default`; a broken one raises BrokenFile."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise BrokenFile(f"{path} on rikki: {e}") from e


def read_cache(path: Path, default: Any) -> Any:
    """Like read_json, but a broken cache is just empty."""
    try:
        return read_json(path, default)
    except BrokenFile:
        return default


def write_json(path: Path, value: Any, private: bool = False) -> None:
    """Writes a temp file next to the target and renames it over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        if private:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
