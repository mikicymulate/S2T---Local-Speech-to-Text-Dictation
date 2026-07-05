"""Global hotkeys: hold-to-talk (press/release) and hands-free toggle."""

import logging

import keyboard

log = logging.getLogger(__name__)


class Hotkeys:
    def __init__(self, hotkey_cfg: dict, on_hold_start, on_hold_stop, on_toggle):
        self._hold_key = hotkey_cfg.get("hold")
        self._toggle_key = hotkey_cfg.get("toggle")
        self._on_hold_start = on_hold_start
        self._on_hold_stop = on_hold_stop
        self._on_toggle = on_toggle
        self._hold_down = False
        self._hooks = []
        self._toggle_handle = None

    def start(self):
        if self._hold_key:
            self._hooks.append(keyboard.on_press_key(self._hold_key, self._pressed))
            self._hooks.append(keyboard.on_release_key(self._hold_key, self._released))
            log.info("Hold-to-talk: hold %r", self._hold_key)
        if self._toggle_key:
            self._toggle_handle = keyboard.add_hotkey(self._toggle_key, self._on_toggle)
            log.info("Toggle recording: press %r", self._toggle_key)

    def _pressed(self, event):
        # OS key-repeat fires press events continuously while held; only act on the first
        if not self._hold_down:
            self._hold_down = True
            self._on_hold_start()

    def _released(self, event):
        if self._hold_down:
            self._hold_down = False
            self._on_hold_stop()

    def stop(self):
        for hook in self._hooks:
            try:
                keyboard.unhook(hook)
            except (KeyError, ValueError):
                pass
        self._hooks = []
        if self._toggle_handle is not None:
            try:
                keyboard.remove_hotkey(self._toggle_handle)
            except (KeyError, ValueError):
                pass
            self._toggle_handle = None
