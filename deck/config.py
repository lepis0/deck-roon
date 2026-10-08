"""Settings in /data/config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .store import data_dir

EXAMPLE = """\
# Deck for Roon
lastfm_api_key = "Last.fm API key"
lastfm_user = "Last.fm-käyttäjänimi"

tidal_client_id = "TIDAL-sovelluksen Client ID"
tidal_client_secret = "TIDAL-sovelluksen Client Secret"
# Sama osoite kuin TIDAL-sovelluksen Redirect URI -kentässä.
tidal_redirect_uri = "http://localhost:8795/tidal/callback"
country = "FI"

# Roon Core. Tyhjänä haetaan lähiverkosta.
roon_host = ""
roon_port = 9330
"""


class ConfigError(Exception):
    """A missing or broken setting, shown to the user as it is."""


PLACEHOLDERS = (
    "Last.fm API key",
    "Last.fm-käyttäjänimi",
    "TIDAL-sovelluksen Client ID",
    "TIDAL-sovelluksen Client Secret",
)


@dataclass
class Config:
    lastfm_api_key: str = ""
    lastfm_user: str = ""
    tidal_client_id: str = ""
    tidal_client_secret: str = ""
    tidal_redirect_uri: str = "http://localhost:8795/tidal/callback"
    country: str = "FI"
    # Keep earlier weekly playlists in TIDAL instead of replacing the previous one.
    tidal_keep_playlists: bool = False
    roon_host: str = ""
    roon_port: int = 9330

    @classmethod
    def path(cls) -> Path:
        return data_dir() / "config.toml"

    @classmethod
    def load(cls) -> "Config":
        """Reads the settings. A missing file is created from EXAMPLE for the user to fill in."""
        path = cls.path()
        if not path.exists():
            path.write_text(EXAMPLE, encoding="utf-8")
        with path.open("rb") as f:
            try:
                values = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"{path} on rikki: {e}") from e
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ConfigError(f"{path}: tuntematon asetus {', '.join(unknown)}")
        return cls(**values)

    def require(self, *names: str) -> None:
        missing = [n for n in names if getattr(self, n) in ("", *PLACEHOLDERS)]
        if missing:
            raise ConfigError(f"Lisää {', '.join(missing)} tiedostoon {self.path()}")
