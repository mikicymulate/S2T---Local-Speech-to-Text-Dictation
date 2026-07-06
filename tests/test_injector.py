"""Tests for s2t.injector.insert_text: the three insert modes and clipboard restore.

keyboard and pyperclip functions are stubbed; time.sleep is neutralised so the tests
don't actually pause. Only the module's functions are patched (not the module object),
so pyperclip.PyperclipException stays a real exception class for the except clauses.
"""

from __future__ import annotations

import pyperclip
import pytest

from s2t import injector


@pytest.fixture
def stub_io(monkeypatch):
    """Stub clipboard + keyboard + sleep; return a recorder of what happened."""
    calls: dict[str, list] = {"copy": [], "send": [], "write": []}
    monkeypatch.setattr(injector.pyperclip, "copy", lambda t: calls["copy"].append(t))
    monkeypatch.setattr(injector.pyperclip, "paste", lambda: "PREVIOUS")
    monkeypatch.setattr(injector.keyboard, "send", lambda k: calls["send"].append(k))
    monkeypatch.setattr(injector.keyboard, "write",
                        lambda t, delay=0: calls["write"].append(t))
    monkeypatch.setattr(injector.time, "sleep", lambda *_a: None)
    return calls


def test_empty_text_does_nothing(stub_io) -> None:
    injector.insert_text("", mode="paste")
    assert stub_io == {"copy": [], "send": [], "write": []}


def test_paste_mode_copies_and_sends_ctrl_v(stub_io) -> None:
    injector.insert_text("hello", mode="paste")
    assert stub_io["copy"] == ["hello"]
    assert stub_io["send"] == ["ctrl+v"]
    assert stub_io["write"] == []


def test_type_mode_writes_keystrokes(stub_io) -> None:
    injector.insert_text("hello", mode="type")
    assert stub_io["copy"] == ["hello"]
    assert stub_io["write"] == ["hello"]
    assert stub_io["send"] == []


def test_clipboard_only_copies_without_keyboard(stub_io) -> None:
    injector.insert_text("hello", mode="clipboard_only")
    assert stub_io["copy"] == ["hello"]
    assert stub_io["send"] == []
    assert stub_io["write"] == []


def test_restore_clipboard_puts_previous_back(stub_io) -> None:
    injector.insert_text("hello", mode="paste", restore_clipboard=True)
    # first the transcript is copied, then the saved previous clipboard is restored
    assert stub_io["copy"] == ["hello", "PREVIOUS"]


def test_paste_aborts_when_clipboard_copy_fails(monkeypatch) -> None:
    sent: list = []

    def failing_copy(_t):
        raise pyperclip.PyperclipException("no clipboard")

    monkeypatch.setattr(injector.pyperclip, "copy", failing_copy)
    monkeypatch.setattr(injector.keyboard, "send", lambda k: sent.append(k))
    monkeypatch.setattr(injector.time, "sleep", lambda *_a: None)

    injector.insert_text("hello", mode="paste")
    assert sent == []  # never pastes a stale clipboard
