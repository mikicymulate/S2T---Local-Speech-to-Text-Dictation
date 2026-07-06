"""Settings/status window: a small tkinter Toplevel that shows whether dictation is on
or off and lets you pick the microphone (with a live level meter) and the LM Studio model.

It is hosted on the overlay's single tkinter thread (see Overlay.run_on_ui), so every
method here runs on that thread. Heavy work (loading a model, writing config) is delegated
to App methods that do it off-thread; this window only reads state the App exposes.
"""

import logging
import tkinter as tk
from tkinter import ttk

from .audio import MicLevelMonitor, list_input_devices

log = logging.getLogger(__name__)

DOT = {
    "off": "#8a8a8e",
    "idle": "#46a758",
    "recording": "#e5484d",
    "processing": "#f5a524",
}
POLL_MS = 150
SERVER_CHECK_MS = 3000


class SettingsWindow:
    _instance: "SettingsWindow | None" = None

    @classmethod
    def show(cls, root, app):
        """Open the window, or focus it if it's already open. Runs on the tk thread."""
        inst = cls._instance
        if inst is not None and inst._win is not None and inst._win.winfo_exists():
            inst._win.deiconify()
            inst._win.lift()
            inst._win.focus_force()
            return
        cls._instance = cls(root, app)

    def __init__(self, root, app):
        self._app = app
        self._monitor: MicLevelMonitor | None = None
        self._monitor_device = object()  # sentinel: forces first build
        self._models_snapshot: list = []
        self._server_ok = None  # None = unknown yet
        self._after_id = None

        win = tk.Toplevel(root)
        self._win = win
        win.title("S2T")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._on_close)
        pad = {"padx": 12, "pady": 6}

        # --- status row -----------------------------------------------------
        status = ttk.Frame(win)
        status.grid(row=0, column=0, sticky="ew", **pad)
        self._dot = tk.Canvas(status, width=16, height=16, highlightthickness=0)
        self._dot_id = self._dot.create_oval(2, 2, 14, 14, fill=DOT["off"], outline="")
        self._dot.grid(row=0, column=0, padx=(0, 8))
        self._status_lbl = ttk.Label(status, text="", font=("Segoe UI", 11, "bold"))
        self._status_lbl.grid(row=0, column=1, sticky="w")
        self._toggle_btn = ttk.Button(status, text="", width=10, command=self._on_toggle)
        self._toggle_btn.grid(row=0, column=2, padx=(16, 0))

        ttk.Separator(win).grid(row=1, column=0, sticky="ew", padx=12)

        # --- microphone -----------------------------------------------------
        mic = ttk.LabelFrame(win, text="Microphone")
        mic.grid(row=2, column=0, sticky="ew", **pad)
        mic.columnconfigure(0, weight=1)
        self._mic_labels: list[str] = []
        self._mic_values: list = []
        self._mic_box = ttk.Combobox(mic, state="readonly", width=42)
        self._mic_box.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self._mic_box.bind("<<ComboboxSelected>>", self._on_mic_selected)
        self._level = ttk.Progressbar(mic, maximum=100, mode="determinate")
        self._level.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._populate_mics()

        # --- model ----------------------------------------------------------
        model = ttk.LabelFrame(win, text="LM Studio model")
        model.grid(row=3, column=0, sticky="ew", **pad)
        model.columnconfigure(0, weight=1)
        self._model_labels: list[str] = []
        self._model_values: list = []
        self._model_box = ttk.Combobox(model, state="readonly", width=42)
        self._model_box.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self._model_box.bind("<<ComboboxSelected>>", self._on_model_selected)
        ttk.Button(model, text="Refresh", command=self._app.refresh_models).grid(
            row=0, column=1, padx=(4, 8), pady=(8, 4))
        self._model_status = ttk.Label(model, text="", foreground="#666")
        self._model_status.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        self._sync_models(force=True)

        win.update_idletasks()
        win.lift()
        win.focus_force()

        self._poll()
        self._schedule_server_check()

    # --- microphone ---------------------------------------------------------

    def _populate_mics(self):
        self._mic_labels = ["System default"]
        self._mic_values = [None]
        for idx, name in list_input_devices():
            self._mic_labels.append(f"{name}")
            self._mic_values.append(idx)
        self._mic_box["values"] = self._mic_labels
        self._mic_box.current(self._current_mic_index())

    def _current_mic_index(self) -> int:
        current = self._app.current_mic()
        if current is None or current == "":
            return 0
        if isinstance(current, int) and current in self._mic_values:
            return self._mic_values.index(current)
        needle = str(current).lower()
        for i, label in enumerate(self._mic_labels):
            if i and needle in label.lower():
                return i
        return 0

    def _on_mic_selected(self, _event=None):
        i = self._mic_box.current()
        if 0 <= i < len(self._mic_values):
            self._app.set_mic_device(self._mic_values[i])

    # --- model --------------------------------------------------------------

    def _sync_models(self, force=False):
        models = self._app.available_models()
        if not force and models == self._models_snapshot:
            return
        self._models_snapshot = list(models)
        self._model_labels = [display for _key, display in models]
        self._model_values = [key for key, _display in models]
        self._model_box["values"] = self._model_labels
        current = self._app.current_model()
        if current in self._model_values:
            self._model_box.current(self._model_values.index(current))
        elif self._model_labels:
            self._model_box.set(current or "")

    def _on_model_selected(self, _event=None):
        i = self._model_box.current()
        if 0 <= i < len(self._model_values):
            self._app.set_lmstudio_model(self._model_values[i])

    # --- periodic refresh ---------------------------------------------------

    def _poll(self):
        if self._win is None or not self._win.winfo_exists():
            return
        app = self._app
        state = app.state if app.enabled else "off"

        self._dot.itemconfigure(self._dot_id, fill=DOT.get(state, DOT["off"]))
        self._status_lbl.configure(text={
            "off": "OFF",
            "idle": "ON — Idle",
            "recording": "Recording…",
            "processing": "Transcribing…",
        }.get(state, "OFF"))
        self._toggle_btn.configure(text="Turn Off" if app.enabled else "Turn On")

        self._update_meter()
        self._sync_models()

        if app.model_loading:
            self._model_status.configure(text="Loading model…", foreground="#b06a00")
        elif self._server_ok is True:
            self._model_status.configure(text="Server: reachable", foreground="#2f7d32")
        elif self._server_ok is False:
            self._model_status.configure(text="Server: unreachable", foreground="#b00020")
        else:
            self._model_status.configure(text="Server: checking…", foreground="#666")

        self._after_id = self._win.after(POLL_MS, self._poll)

    def _update_meter(self):
        """Run the level monitor only while idle so it never fights the Recorder."""
        want = self._app.state == "idle"
        device = self._app.current_mic()
        if self._monitor is not None and device != self._monitor_device:
            self._monitor.stop()
            self._monitor = None
        if want:
            if self._monitor is None:
                self._monitor = MicLevelMonitor(device)
                self._monitor_device = device
                self._monitor.start()
            self._level.configure(value=self._monitor.level * 100)
        else:
            if self._monitor is not None:
                self._monitor.stop()
                self._monitor = None
                self._monitor_device = object()
            self._level.configure(value=0)

    def _schedule_server_check(self):
        if self._win is None or not self._win.winfo_exists():
            return
        # server_reachable() does a blocking GET; run it off the tk thread. The thread
        # must NOT touch any tk widget (not thread-safe) — it only sets a plain attribute
        # that the tk-thread poll loop reads.
        import threading

        def check():
            self._server_ok = self._app.server_reachable()

        threading.Thread(target=check, name="server-check", daemon=True).start()
        self._win.after(SERVER_CHECK_MS, self._schedule_server_check)

    # --- actions ------------------------------------------------------------

    def _on_toggle(self):
        self._app.set_enabled(not self._app.enabled)

    def _on_close(self):
        if self._after_id is not None:
            try:
                self._win.after_cancel(self._after_id)
            except Exception:
                pass
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        win, self._win = self._win, None
        if win is not None:
            win.destroy()
        SettingsWindow._instance = None
