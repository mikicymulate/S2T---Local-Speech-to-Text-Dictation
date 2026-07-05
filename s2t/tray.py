"""System tray icon. The icon color reflects the app state; the menu controls the app.
pystray's run() owns the main thread."""

import logging
import os

import pystray
from PIL import Image, ImageDraw

from .config import CONFIG_PATH, HISTORY_PATH

log = logging.getLogger(__name__)

COLORS = {
    "idle": (120, 120, 128),
    "recording": (229, 72, 77),
    "processing": (245, 165, 36),
    "disabled": (60, 60, 64),
}


def _make_image(color) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), fill=color + (255,))
    # small mic glyph: rounded bar + stand
    draw.rounded_rectangle((26, 16, 38, 36), radius=6, fill=(255, 255, 255, 255))
    draw.arc((20, 24, 44, 44), start=0, end=180, fill=(255, 255, 255, 255), width=3)
    draw.line((32, 44, 32, 50), fill=(255, 255, 255, 255), width=3)
    return img


class Tray:
    def __init__(self, app):
        self._app = app
        self._images = {state: _make_image(color) for state, color in COLORS.items()}
        menu = pystray.Menu(
            pystray.MenuItem(
                "Enabled",
                lambda icon, item: self._app.set_enabled(not self._app.enabled),
                checked=lambda item: self._app.enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open config", lambda icon, item: os.startfile(CONFIG_PATH)),
            pystray.MenuItem("Reload config", lambda icon, item: self._app.reload_config()),
            pystray.MenuItem("Open history", lambda icon, item: self._open_history()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self._app.quit()),
        )
        self._icon = pystray.Icon("s2t", self._images["idle"], "S2T — idle", menu)

    def _open_history(self):
        HISTORY_PATH.touch(exist_ok=True)
        os.startfile(HISTORY_PATH)

    def set_state(self, state: str):
        image = self._images.get(state)
        if image is not None:
            self._icon.icon = image
            self._icon.title = f"S2T — {state}"

    def run(self):
        """Blocks until stop() is called."""
        self._icon.run()

    def stop(self):
        self._icon.stop()
