"""Floating status pill: a small borderless always-on-top window near the bottom of the
screen showing the current dictation state. Runs its own tkinter loop on a daemon thread;
other threads talk to it through a queue."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from typing import Any, Callable

log = logging.getLogger(__name__)

STATES: dict[str, tuple[str, str]] = {
    "recording": ("●  Recording", "#e5484d"),
    "processing": ("…  Transcribing", "#f5a524"),
    "done": ("✓  Inserted", "#46a758"),
    "error": ("✕  Error", "#e5484d"),
}
BG = "#1c1c1e"
AUTO_HIDE_MS = 1400  # for "done" / "error"


class Overlay:
    def __init__(self):
        # holds either a state string, the "__quit__" sentinel, or a ("call", fn) tuple
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="overlay", daemon=True)
        self._thread.start()

    def set_state(self, state: str) -> None:
        """state: one of STATES keys, or 'hidden'."""
        self._queue.put(state)

    def run_on_ui(self, fn: Callable[[tk.Tk], object]) -> None:
        """Schedule fn(root) to run on the tkinter thread. Use this to build/show
        other windows (e.g. the settings window) safely from any thread."""
        self._queue.put(("call", fn))

    def stop(self) -> None:
        self._queue.put("__quit__")

    # --- tkinter thread ----------------------------------------------------

    def _run(self) -> None:
        try:
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.93)
            root.configure(bg=BG)
            label = tk.Label(
                root, text="", bg=BG, fg="white",
                font=("Segoe UI", 11, "bold"), padx=18, pady=8,
            )
            label.pack()
            root.withdraw()
            hide_job: list[str | None] = [None]

            def place() -> None:
                root.update_idletasks()
                w, h = root.winfo_reqwidth(), root.winfo_reqheight()
                x = (root.winfo_screenwidth() - w) // 2
                y = root.winfo_screenheight() - h - 90
                root.geometry(f"{w}x{h}+{x}+{y}")

            def apply(state: str) -> None:
                if hide_job[0] is not None:
                    root.after_cancel(hide_job[0])
                    hide_job[0] = None
                if state == "hidden":
                    root.withdraw()
                    return
                text, color = STATES[state]
                label.configure(text=text, fg=color)
                place()
                root.deiconify()
                root.attributes("-topmost", True)
                if state in ("done", "error"):
                    hide_job[0] = root.after(AUTO_HIDE_MS, root.withdraw)

            def poll() -> None:
                try:
                    while True:
                        item = self._queue.get_nowait()
                        if item == "__quit__":
                            root.destroy()
                            return
                        if isinstance(item, tuple) and item[0] == "call":
                            try:
                                item[1](root)
                            except Exception:
                                log.exception("UI callback failed")
                            continue
                        apply(item)
                except queue.Empty:
                    pass
                root.after(50, poll)

            poll()
            root.mainloop()
        except Exception:
            log.exception("Overlay thread crashed; dictation still works without it")
