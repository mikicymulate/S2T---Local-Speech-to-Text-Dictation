"""Tests for s2t.hotkeys: hold-key press/release de-duplication and capture_hotkey.

The global keyboard hook is faked: capture_hotkey's hook() is replaced with a stub that
drives the registered callback with synthetic key events, so nothing touches real input.
"""

from __future__ import annotations

from types import SimpleNamespace

import keyboard

from s2t import hotkeys
from s2t.hotkeys import Hotkeys, capture_hotkey


# --- Hotkeys press/release logic -------------------------------------------

def make_hotkeys() -> tuple[Hotkeys, dict[str, int]]:
    counts = {"start": 0, "stop": 0, "toggle": 0}
    hk = Hotkeys(
        {"hold": "right ctrl", "toggle": "f8"},
        on_hold_start=lambda: counts.__setitem__("start", counts["start"] + 1),
        on_hold_stop=lambda: counts.__setitem__("stop", counts["stop"] + 1),
        on_toggle=lambda: counts.__setitem__("toggle", counts["toggle"] + 1),
    )
    return hk, counts


def test_hold_press_fires_start_once_despite_key_repeat() -> None:
    hk, counts = make_hotkeys()
    hk._pressed(None)   # first key-down
    hk._pressed(None)   # OS auto-repeat while held
    hk._pressed(None)
    assert counts["start"] == 1
    assert counts["stop"] == 0


def test_hold_release_fires_stop_once() -> None:
    hk, counts = make_hotkeys()
    hk._pressed(None)
    hk._released(None)
    hk._released(None)  # a stray second release must not re-fire
    assert counts["start"] == 1
    assert counts["stop"] == 1


def test_release_without_press_is_ignored() -> None:
    hk, counts = make_hotkeys()
    hk._released(None)
    assert counts["stop"] == 0


# --- capture_hotkey --------------------------------------------------------

def _drive(monkeypatch, events: list[SimpleNamespace]) -> None:
    """Make keyboard.hook(cb) synchronously feed `events` to cb, then no-op unhook."""
    def fake_hook(cb):
        for ev in events:
            cb(ev)
        return "HOOK"

    monkeypatch.setattr(hotkeys.keyboard, "hook", fake_hook)
    monkeypatch.setattr(hotkeys.keyboard, "unhook", lambda _h: None)


def down(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, event_type=keyboard.KEY_DOWN)


def up(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, event_type=keyboard.KEY_UP)


def test_capture_single_key(monkeypatch) -> None:
    _drive(monkeypatch, [down("a")])
    assert capture_hotkey(combo=False, timeout=1.0) == "a"


def test_capture_esc_reports_cancel_sentinel(monkeypatch) -> None:
    _drive(monkeypatch, [down("esc")])
    assert capture_hotkey(combo=False, timeout=1.0) == "esc"


def test_capture_ignores_events_without_a_name(monkeypatch) -> None:
    _drive(monkeypatch, [SimpleNamespace(name=None, event_type=keyboard.KEY_DOWN),
                         down("b")])
    assert capture_hotkey(combo=False, timeout=1.0) == "b"


def test_capture_combo_collects_until_first_release(monkeypatch) -> None:
    _drive(monkeypatch, [down("ctrl"), down("alt"), down("space"), up("ctrl")])
    assert capture_hotkey(combo=True, timeout=1.0) == "ctrl+alt+space"


def test_capture_combo_deduplicates_held_keys(monkeypatch) -> None:
    _drive(monkeypatch, [down("ctrl"), down("ctrl"), down("space"), up("space")])
    assert capture_hotkey(combo=True, timeout=1.0) == "ctrl+space"


def test_capture_returns_none_on_timeout(monkeypatch) -> None:
    _drive(monkeypatch, [])  # no events fired
    assert capture_hotkey(combo=False, timeout=0.05) is None
