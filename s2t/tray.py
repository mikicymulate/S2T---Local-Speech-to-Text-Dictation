"""System tray icon. The icon color reflects the app state; the menu controls the app.
pystray's run() owns the main thread."""

import logging
import os

import pystray
from PIL import Image, ImageDraw

from .config import CONFIG_PATH, HISTORY_PATH

log = logging.getLogger(__name__)

COLORS = {
    "idle": (70, 167, 88),  # green: on and ready
    "recording": (229, 72, 77),
    "processing": (245, 165, 36),
    "disabled": (128, 128, 134),  # gray: dictation turned off
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
            pystray.MenuItem("Settings…", lambda icon, item: self._app.open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Microphone", pystray.Menu(self._mic_items)),
            pystray.MenuItem("Model", pystray.Menu(self._model_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open config", lambda icon, item: os.startfile(CONFIG_PATH)),
            pystray.MenuItem("Reload config", lambda icon, item: self._app.reload_config()),
            pystray.MenuItem("Open history", lambda icon, item: self._open_history()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self._app.quit()),
        )
        self._icon = pystray.Icon("s2t", self._images["idle"], "S2T — idle", menu)

    # Dynamic submenus: pystray calls these each time the menu is shown, so they
    # always reflect the currently available devices/models and the active choice.
    # pystray rejects actions with more than 2 args, so the selected value is bound
    # as a closure free variable (a factory) rather than a default argument.

    def _pick_mic(self, value):
        return lambda icon, item: self._app.set_mic_device(value)

    def _pick_model(self, key):
        return lambda icon, item: self._app.set_lmstudio_model(key)

    def _mic_items(self):
        yield pystray.MenuItem(
            "System default",
            self._pick_mic(None),
            checked=lambda item: self._app.current_mic() in (None, ""),
            radio=True,
        )
        for idx, name in self._app.available_mics():
            yield pystray.MenuItem(
                name,
                self._pick_mic(idx),
                checked=lambda item, i=idx: self._app.current_mic() == i,
                radio=True,
            )

    def _model_items(self):
        models = self._app.available_models()
        if not models:
            yield pystray.MenuItem(self._app.current_model() or "(no models)", None, enabled=False)
            return
        for key, display in models:
            yield pystray.MenuItem(
                display,
                self._pick_model(key),
                checked=lambda item, k=key: self._app.current_model() == k,
                radio=True,
            )

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
