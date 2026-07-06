"""Get the final text into the app the user was dictating into.

Modes:
  paste          - copy to clipboard and send Ctrl+V to the focused window (most reliable)
  type           - simulate keystrokes character by character (for apps that block paste)
  clipboard_only - just copy; the user pastes manually
"""

from __future__ import annotations

import logging
import time

import keyboard
import pyperclip

from .config import InsertMode

log = logging.getLogger(__name__)


def insert_text(text: str, mode: InsertMode = "paste", restore_clipboard: bool = False) -> None:
    if not text:
        return

    previous = None
    if restore_clipboard:
        try:
            previous = pyperclip.paste()
        except pyperclip.PyperclipException:
            previous = None

    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        log.error("Clipboard copy failed: %s", exc)
        if mode != "type":
            return

    if mode == "paste":
        time.sleep(0.15)  # let the clipboard settle and any hotkey modifiers clear
        keyboard.send("ctrl+v")
        time.sleep(0.3)
    elif mode == "type":
        time.sleep(0.15)
        keyboard.write(text, delay=0.005)

    if restore_clipboard and previous is not None:
        time.sleep(0.2)
        try:
            pyperclip.copy(previous)
        except pyperclip.PyperclipException:
            pass
