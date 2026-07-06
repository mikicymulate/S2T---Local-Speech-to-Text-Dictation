"""Wires everything together and runs the dictation state machine:

    IDLE -> RECORDING -> PROCESSING (transcribe -> clean -> insert) -> IDLE
"""

from __future__ import annotations

import json
import logging
import threading
import time
import winsound
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal

import numpy as np

from . import injector, winperf
from .audio import Recorder, SAMPLE_RATE, list_input_devices
from .config import Config, HISTORY_PATH, MicDevice, load_config, save_config
from .formatter import Formatter, list_models
from .hotkeys import Hotkeys, capture_hotkey
from .overlay import Overlay
from .settings_window import SettingsWindow
from .transcriber import Transcriber

if TYPE_CHECKING:
    from .tray import Tray

log = logging.getLogger(__name__)

# The three states of the dictation machine. UI/tray states ("done", "error",
# "hidden", "disabled") are distinct transient labels, not values of _state.
State = Literal["idle", "recording", "processing"]
HotkeyKind = Literal["hold", "toggle"]

IDLE: Final[State] = "idle"
RECORDING: Final[State] = "recording"
PROCESSING: Final[State] = "processing"
MIN_AUDIO_SECONDS = 0.3


class App:
    def __init__(self, cfg: Config):
        self.enabled = True
        self.tray: Tray | None = None  # set by main() after construction
        self.model_loading = False  # read by the settings window
        # None, "hold", or "toggle"; read by the settings window
        self.hotkey_capturing: HotkeyKind | None = None
        self.hotkey_status = ""  # transient message ("Cancelled", "Timed out", ...)
        self._models_cache: list[tuple[str, str]] = []
        self._state: State = IDLE
        self._state_lock = threading.Lock()
        self._build(cfg)
        self._overlay = Overlay()

    @property
    def state(self) -> State:
        return self._state

    def _build(self, cfg: Config) -> None:
        self._cfg = cfg
        self._recorder = Recorder(cfg["mic_device"], cfg["max_record_seconds"])
        self._transcriber = Transcriber(cfg["whisper"])
        self._formatter = Formatter(cfg["lmstudio"], cfg["dictionary"])
        self._hotkeys = self._make_hotkeys()

    def _make_hotkeys(self) -> Hotkeys:
        return Hotkeys(
            self._cfg["hotkeys"],
            on_hold_start=self._begin_recording,
            on_hold_stop=self._finish_recording,
            on_toggle=self._toggle,
        )

    def start(self) -> None:
        self._overlay.start()
        self._hotkeys.start()
        # warm up the heavy pieces in the background so the first dictation is snappy
        threading.Thread(target=self._warm_up, name="warmup", daemon=True).start()

    def _warm_up(self) -> None:
        try:
            self._transcriber.load()
        except Exception:
            log.exception("Failed to load Whisper model")
        self._formatter.ensure_server()
        winperf.unthrottle_lmstudio()
        self.refresh_models()

    # --- hotkey callbacks (must return fast) -------------------------------

    def _begin_recording(self) -> None:
        with self._state_lock:
            if not self.enabled or self._state != IDLE:
                return
            self._state = RECORDING
        try:
            self._recorder.start()
        except Exception:
            log.exception("Could not start recording (mic in use / not found?)")
            with self._state_lock:
                self._state = IDLE
            self._set_ui("error")
            return
        self._beep(880)
        self._set_ui(RECORDING)

    def _finish_recording(self) -> None:
        with self._state_lock:
            if self._state != RECORDING:
                return
            self._state = PROCESSING
        audio = self._recorder.stop()
        self._beep(520)
        self._set_ui(PROCESSING)
        threading.Thread(target=self._process, args=(audio,), name="process", daemon=True).start()

    def _toggle(self) -> None:
        if self._state == RECORDING:
            self._finish_recording()
        else:
            self._begin_recording()

    # --- pipeline -----------------------------------------------------------

    def _process(self, audio: np.ndarray) -> None:
        try:
            if audio.size < MIN_AUDIO_SECONDS * SAMPLE_RATE:
                self._set_ui("hidden")
                return
            started = time.monotonic()
            raw = self._transcriber.transcribe(audio)
            if not raw:
                log.info("No speech detected")
                self._set_ui("hidden")
                return
            text = self._formatter.clean(raw)
            injector.insert_text(
                text,
                mode=self._cfg["insert_mode"],
                restore_clipboard=self._cfg["restore_clipboard"],
            )
            self._append_history(audio.size / SAMPLE_RATE, raw, text)
            log.info("Done in %.1fs: %r", time.monotonic() - started, text)
            self._set_ui("done")
        except Exception:
            log.exception("Dictation pipeline failed")
            self._set_ui("error")
        finally:
            with self._state_lock:
                self._state = IDLE
            if self.tray:
                self.tray.set_state(IDLE if self.enabled else "disabled")

    def _append_history(self, seconds: float, raw: str, cleaned: str) -> None:
        try:
            entry = {
                "time": datetime.now().isoformat(timespec="seconds"),
                "seconds": round(seconds, 1),
                "raw": raw,
                "text": cleaned,
            }
            with open(HISTORY_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            log.exception("Could not write history")

    # --- UI helpers ----------------------------------------------------------

    def _set_ui(self, state: str) -> None:
        self._overlay.set_state(state if state in ("recording", "processing", "done", "error", "hidden") else "hidden")
        if self.tray:
            if state in (RECORDING, PROCESSING):
                self.tray.set_state(state)
            else:
                self.tray.set_state(IDLE if self.enabled else "disabled")

    def _beep(self, freq: int) -> None:
        if self._cfg["sound_cues"]:
            threading.Thread(
                target=winsound.Beep, args=(freq, 120), daemon=True,
            ).start()

    # --- tray actions ----------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled and self._state == RECORDING:
            self._recorder.stop()
            with self._state_lock:
                self._state = IDLE
            self._set_ui("hidden")
        if self.tray:
            self.tray.set_state("idle" if enabled else "disabled")
        log.info("Dictation %s", "enabled" if enabled else "disabled")

    def open_settings(self) -> None:
        """Show the status/settings window (marshalled onto the tkinter thread)."""
        self._overlay.run_on_ui(lambda root: SettingsWindow.show(root, self))

    # --- microphone -----------------------------------------------------------

    def available_mics(self) -> list[tuple[int, str]]:
        return list_input_devices()

    def current_mic(self) -> MicDevice:
        return self._cfg["mic_device"]

    def set_mic_device(self, device: MicDevice) -> None:
        if device == self._cfg["mic_device"]:
            return
        self._cfg["mic_device"] = device
        save_config(self._cfg)
        if self._recorder.recording:
            try:
                self._recorder.stop()
            except Exception:
                log.debug("Error stopping recorder on mic change", exc_info=True)
            with self._state_lock:
                self._state = IDLE
            self._set_ui("hidden")
        # only the recorder depends on the mic; leave Whisper/LM Studio untouched
        self._recorder = Recorder(device, self._cfg["max_record_seconds"])
        log.info("Microphone set to %r", device)

    # --- LM Studio model ------------------------------------------------------

    def available_models(self) -> list[tuple[str, str]]:
        return list(self._models_cache)

    def current_model(self) -> str:
        return self._cfg["lmstudio"]["model"]

    def server_reachable(self) -> bool:
        return self._formatter.server_reachable()

    def refresh_models(self) -> None:
        def work() -> None:
            try:
                self._models_cache = list_models(self._cfg["lmstudio"])
            except Exception:
                log.exception("Could not refresh model list")
        threading.Thread(target=work, name="refresh-models", daemon=True).start()

    def set_lmstudio_model(self, model: str) -> None:
        if not model or model == self._cfg["lmstudio"]["model"]:
            return
        # the formatter holds a reference to cfg["lmstudio"], so this also updates it
        self._cfg["lmstudio"]["model"] = model
        save_config(self._cfg)
        log.info("Switching LM Studio model to %r", model)

        def work() -> None:
            self.model_loading = True
            try:
                self._formatter.ensure_server()  # loads the model + warms it up
            except Exception:
                log.exception("Could not load model %r", model)
            finally:
                self.model_loading = False
        threading.Thread(target=work, name="load-model", daemon=True).start()

    # --- hotkeys ----------------------------------------------------------------

    def current_hotkeys(self) -> dict[str, str]:
        hk = self._cfg["hotkeys"]
        return {"hold": hk["hold"], "toggle": hk["toggle"]}

    def start_hotkey_capture(self, kind: HotkeyKind) -> None:
        """kind: 'hold' or 'toggle'. Waits (in the background) for the user to press the
        new key — a combo like ctrl+alt+space is allowed for toggle — then rebinds and
        persists it. The settings window polls hotkey_capturing / hotkey_status."""
        if self.hotkey_capturing or self._state != IDLE:
            return
        self.hotkey_capturing = kind
        self.hotkey_status = ""
        threading.Thread(
            target=self._capture_hotkey, args=(kind,), name="hotkey-capture", daemon=True,
        ).start()

    def _capture_hotkey(self, kind: HotkeyKind) -> None:
        old = self._cfg["hotkeys"][kind]
        try:
            # unhook current bindings so pressing them during capture doesn't dictate
            self._hotkeys.stop()
            key = capture_hotkey(combo=(kind == "toggle"), timeout=10.0)
            if key is None:
                self.hotkey_status = "Timed out — try again"
            elif key == "esc":
                self.hotkey_status = "Cancelled"
            else:
                other: HotkeyKind = "toggle" if kind == "hold" else "hold"
                if key == self._cfg["hotkeys"].get(other):
                    self.hotkey_status = f"'{key}' is already the {other} key"
                else:
                    self._cfg["hotkeys"][kind] = key
                    save_config(self._cfg)
                    log.info("Hotkey %r set to %r", kind, key)
        except Exception:
            log.exception("Hotkey capture failed")
            self.hotkey_status = "Capture failed (see log)"
        finally:
            try:
                self._hotkeys = self._make_hotkeys()
                self._hotkeys.start()
            except Exception:
                # e.g. the keyboard library rejects the captured key name: revert
                log.exception("Could not bind %r; reverting to %r", kind, old)
                self.hotkey_status = "Key not bindable — reverted"
                self._cfg["hotkeys"][kind] = old
                save_config(self._cfg)
                self._hotkeys = self._make_hotkeys()
                self._hotkeys.start()
            self.hotkey_capturing = None

    def reload_config(self) -> None:
        log.info("Reloading config...")
        self._hotkeys.stop()
        self._build(load_config())
        self._hotkeys.start()
        threading.Thread(target=self._warm_up, name="warmup", daemon=True).start()

    def quit(self) -> None:
        log.info("Quitting")
        self._hotkeys.stop()
        if self._recorder.recording:
            self._recorder.stop()
        self._overlay.stop()
        if self.tray:
            self.tray.stop()
