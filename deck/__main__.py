"""The `deck` command."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__


def main() -> None:
    parser = argparse.ArgumentParser(prog="deck", description="Viikon levysuositukset Rooniin.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="käynnistää web-sivun")
    serve.add_argument("--port", type=int, default=int(os.environ.get("DECK_PORT", "8795")))
    sub.add_parser("taste", help="tulostaa makuprofiilin JSONina (viikkoajon käyttöön)")
    curate = sub.add_parser("curate", help="viikkoajon komennot")
    curate_sub = curate.add_subparsers(dest="curate_command", required=True)
    submit = curate_sub.add_parser("submit", help="tarkistaa ehdokkaat (stdin) ja kirjoittaa listan")
    submit.add_argument("--dry-run", action="store_true", help="vain tarkistus, listaa ei kirjoiteta")
    sub.add_parser("playlist", help="luo viikon listasta TIDAL-soittolistan")
    tidal = sub.add_parser("tidal", help="TIDAL-kirjautuminen")
    tidal_sub = tidal.add_subparsers(dest="tidal_command", required=True)
    tidal_sub.add_parser("login", help="tulostaa kirjautumisosoitteen")
    finish = tidal_sub.add_parser("finish", help="viimeistelee kirjautumisen uudelleenohjausosoitteesta")
    finish.add_argument("url")

    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("DECK_LOG", "INFO"), stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL, and Last.fm URLs carry the API key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from .config import ConfigError
    from .store import BrokenFile

    try:
        run(args)
    except (ConfigError, BrokenFile) as e:
        sys.exit(str(e))


def run(args: argparse.Namespace) -> None:

    if args.command == "serve":
        import uvicorn

        uvicorn.run("deck.web:app", host="0.0.0.0", port=args.port, log_level="info")
    elif args.command == "taste":
        from .curate import taste

        taste()
    elif args.command == "curate":
        from .curate import submit as do_submit

        do_submit(args.dry_run)
    elif args.command == "playlist":
        from .config import Config
        from .curate import sync_playlist

        print(sync_playlist(Config.load()))
    elif args.command == "tidal":
        from .config import Config
        from .tidal import Tidal

        t = Tidal(Config.load())
        if args.tidal_command == "login":
            print(t.login_url())
        else:
            t.finish_login(args.url)
            print("TIDAL-kirjautuminen tallennettu.")


if __name__ == "__main__":
    main()
