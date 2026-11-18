from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bookcoder",
        description="BookCoder — Professional AI Audiobook Generator",
    )
    parser.add_argument("--host", default=os.environ.get("BOOKCODER_HOST", "127.0.0.1"), help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("BOOKCODER_PORT", "8765")), help="Port to listen on (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the application in a web browser automatically")
    parser.add_argument("--debug", action="store_true", help="Run the web server in debug mode")
    args = parser.parse_args()

    from .ui.server import run

    run(host=args.host, port=args.port, debug=args.debug, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
