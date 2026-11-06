import argparse
import sys

import uvicorn

from . import setup

HOST = "127.0.0.1"
PORT = 8787


def main() -> None:
    parser = argparse.ArgumentParser(prog="paper-translator", description="英語論文の PDF をローカルで和訳する")
    parser.add_argument("command", nargs="?", choices=["serve", "setup"], default="serve")
    if parser.parse_args().command == "setup":
        sys.exit(setup.main())
    uvicorn.run(
        "paper_translator.app:default_app",
        factory=True,
        host=HOST,
        port=PORT,
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
