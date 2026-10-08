"""Name comparison shared by Last.fm, TIDAL and Roon matching."""

from __future__ import annotations

import re
import unicodedata


def _strip_brackets(name: str) -> str:
    out, depth = [], 0
    for c in name:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(c)
    return "".join(out)


def normalize(name: str) -> str:
    """Lowercase, accents removed (ä → a), & → and, punctuation removed and bracketed
    extras skipped: "OK Computer (Remastered)" = "ok computer". A name made only of
    brackets keeps what is inside them. A " - 2011 Remaster" style suffix is dropped."""
    source = _strip_brackets(name)
    if not source.strip():
        source = name
    source = re.split(r"\s[-–]\s(?=.*(remaster|edition|version|deluxe|mono|stereo|expanded|anniversary))",
                      source, maxsplit=1, flags=re.I)[0]
    out = []
    for c in unicodedata.normalize("NFD", source):
        if unicodedata.combining(c):
            continue
        if c == "&":
            out.append(" and ")
        elif c.isalnum():
            out.append(c.lower())
        elif c.isspace() or c in "-/":
            out.append(" ")
    return " ".join("".join(out).split())


def same_album(artist_a: str, album_a: str, artist_b: str, album_b: str) -> bool:
    return normalize(artist_a) == normalize(artist_b) and normalize(album_a) == normalize(album_b)


def plain_artist(roon_subtitle: str | None) -> str:
    """Roon writes artists as "[[3388026|Gene Clark]]"; this keeps the names."""
    if not roon_subtitle:
        return ""
    return re.sub(r"\[\[\d+\|([^\]]*)\]\]", r"\1", roon_subtitle)
