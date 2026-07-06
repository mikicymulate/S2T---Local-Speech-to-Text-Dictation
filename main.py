"""S2T — local Speech-to-Text-style dictation.

Run:  python main.py
Hold right Ctrl (default) to dictate into any app; press F8 to toggle hands-free mode.
"""

from __future__ import annotations

import logging
import sys

from s2t.app import App
from s2t.config import LOG_PATH, load_config
from s2t.tray import Tray


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    cfg = load_config()
    app = App(cfg)
    tray = Tray(app)
    app.tray = tray
    app.start()
    logging.getLogger(__name__).info(
        "S2T running. Hold %r to dictate, press %r to toggle hands-free.",
        cfg["hotkeys"]["hold"], cfg["hotkeys"]["toggle"],
    )
    tray.run()  # blocks until Quit


if __name__ == "__main__":
    main()
