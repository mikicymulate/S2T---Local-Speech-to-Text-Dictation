"""Wires everything together and runs the dictation state machine:

    IDLE -> RECORDING -> PROCESSING (transcribe -> clean -> insert) -> IDLE
"""

import json
import logging
import threading
import time
import winsound
from datetime import datetime

from . import injector, winperf
from .audio import Recorder, SAMPLE_RATE, list_input_devices
from .config import HISTORY_PATH, load_config, save_config
from .formatter import Formatter, list_models
from .hotkeys import Hotkeys
from .overlay import Overlay
from .settings_window import SettingsWindow
from .transcriber import Transcriber

log = logging.getLogger(__name__)

IDLE, RECORDING, PROCESSING = "idle", "recording", "processing"
MIN_AUDIO_SECONDS = 0.3


class App:
    def __init__(self, cfg: dict):
        self.enabled = True
        self.tray = None  # set by main() after construction
        self.model_loading = False  # read by the settings window
        self._models_cache: list = []
        self._state = IDLE
        self._state_lock = threading.Lock()
        self._build(cfg)
        self._overlay = Overlay()

    @property
    def state(self) -> str:
        return self._state

    def _build(self, cfg: dict):
        self._cfg = cfg
        self._recorder = Recorder(cfg["mic_device"], cfg["max_record_seconds"])
        self._transcriber = Transcriber(cfg["whisper"])
        self._formatter = Formatter(cfg["lmstudio"], cfg["dictionary"])
        self._hotkeys = Hotkeys(
            cfg["hotkeys"],
            on_hold_start=self._begin_recording,
            on_hold_stop=self._finish_recording,
            on_toggle=self._toggle,
        )

    def start(self):
        self._overlay.start()
        self._hotkeys.start()
        # warm up the heavy pieces in the background so the first dictation is snappy
        threading.Thread(target=self._warm_up, name="warmup", daemon=True).start()

    def _warm_up(self):
        try:
            self._transcriber.load()
        except Exception:
            log.exception("Failed to load Whisper model")
        self._formatter.ensure_server()
        winperf.unthrottle_lmstudio()
        self.refresh_models()

    # --- hotkey callbacks (must return fast) -------------------------------

    def _begin_recording(self):
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

    def _finish_recording(self):
        with self._state_lock:
            if self._state != RECORDING:
                return
            self._state = PROCESSING
        audio = self._recorder.stop()
        self._beep(520)
        self._set_ui(PROCESSING)
        threading.Thread(target=self._process, args=(audio,), name="process", daemon=True).start()

    def _toggle(self):
        if self._state == RECORDING:
            self._finish_recording()
        else:
            self._begin_recording()

    # --- pipeline -----------------------------------------------------------

    def _process(self, audio):
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

    def _append_history(self, seconds: float, raw: str, cleaned: str):
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

    def _set_ui(self, state: str):
        self._overlay.set_state(state if state in ("recording", "processing", "done", "error", "hidden") else "hidden")
        if self.tray:
            if state in (RECORDING, PROCESSING):
                self.tray.set_state(state)
            else:
                self.tray.set_state(IDLE if self.enabled else "disabled")

    def _beep(self, freq: int):
        if self._cfg["sound_cues"]:
            threading.Thread(
                target=winsound.Beep, args=(freq, 120), daemon=True,
            ).start()

    # --- tray actions ----------------------------------------------------------

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        if not enabled and self._state == RECORDING:
            self._recorder.stop()
            with self._state_lock:
                self._state = IDLE
            self._set_ui("hidden")
        if self.tray:
            self.tray.set_state("idle" if enabled else "disabled")
        log.info("Dictation %s", "enabled" if enabled else "disabled")

    def open_settings(self):
        """Show the status/settings window (marshalled onto the tkinter thread)."""
        self._overlay.run_on_ui(lambda root: SettingsWindow.show(root, self))

    # --- microphone -----------------------------------------------------------

    def available_mics(self):
        return list_input_devices()

    def current_mic(self):
        return self._cfg["mic_device"]

    def set_mic_device(self, device):
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

    def available_models(self):
        return list(self._models_cache)

    def current_model(self):
        return self._cfg["lmstudio"]["model"]

    def server_reachable(self) -> bool:
        return self._formatter.server_reachable()

    def refresh_models(self):
        def work():
            try:
                self._models_cache = list_models(self._cfg["lmstudio"])
            except Exception:
                log.exception("Could not refresh model list")
        threading.Thread(target=work, name="refresh-models", daemon=True).start()

    def set_lmstudio_model(self, model):
        if not model or model == self._cfg["lmstudio"]["model"]:
            return
        # the formatter holds a reference to cfg["lmstudio"], so this also updates it
        self._cfg["lmstudio"]["model"] = model
        save_config(self._cfg)
        log.info("Switching LM Studio model to %r", model)

        def work():
            self.model_loading = True
            try:
                self._formatter.ensure_server()  # loads the model + warms it up
            except Exception:
                log.exception("Could not load model %r", model)
            finally:
                self.model_loading = False
        threading.Thread(target=work, name="load-model", daemon=True).start()

    def reload_config(self):
        log.info("Reloading config...")
        self._hotkeys.stop()
        self._build(load_config())
        self._hotkeys.start()
        threading.Thread(target=self._warm_up, name="warmup", daemon=True).start()

    def quit(self):
        log.info("Quitting")
        self._hotkeys.stop()
        if self._recorder.recording:
            self._recorder.stop()
        self._overlay.stop()
        if self.tray:
            self.tray.stop()
