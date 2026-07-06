"""Microphone capture: 16 kHz mono float32, buffered in memory between start() and stop()."""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
import sounddevice as sd

from .config import MicDevice

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what Whisper expects


def resolve_device(mic_device: MicDevice) -> int | None:
    """Accept a device index, a name substring, or None for the system default."""
    if mic_device is None or mic_device == "":
        return None
    if isinstance(mic_device, int):
        return mic_device
    needle = str(mic_device).lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
            return idx
    log.warning("Mic device %r not found; using system default", mic_device)
    return None


def list_input_devices() -> list[tuple[int, str]]:
    """Every capture-capable device as (index, name), for the mic picker."""
    devices = []
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append((idx, dev["name"]))
    except Exception:
        log.exception("Could not enumerate input devices")
    return devices


class MicLevelMonitor:
    """Opens a lightweight input stream and exposes the current RMS level (0..1),
    so a UI can show whether the selected mic is picking up sound. Independent of
    the Recorder — pause it while a real dictation is recording."""

    def __init__(self, device: MicDevice = None):
        self._device = resolve_device(device)
        self._stream: sd.InputStream | None = None
        self.level = 0.0

    def _callback(self, indata: np.ndarray, _frames: int, _time_info: Any, status: Any) -> None:
        if status:
            log.debug("Level monitor status: %s", status)
        rms = float(np.sqrt(np.mean(np.square(indata[:, 0]))))
        # decay the previous value so the bar falls smoothly; gain so normal speech
        # (RMS ~0.02–0.1 in float32) lands in a clearly visible range
        self.level = min(1.0, max(self.level * 0.6, rms * 8.0))

    def start(self) -> None:
        if self._stream is not None:
            return
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self._device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            log.exception("Could not start mic level monitor")
            self._stream = None

    def stop(self) -> None:
        self.level = 0.0
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            log.debug("Error stopping level monitor", exc_info=True)
        finally:
            self._stream = None


class Recorder:
    def __init__(self, mic_device: MicDevice = None, max_seconds: float = 300):
        self._device = resolve_device(mic_device)
        self._max_samples = int(max_seconds * SAMPLE_RATE)
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []
            self._samples = 0
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self._device,
                callback=self._callback,
            )
            self._stream.start()

    def _callback(self, indata: np.ndarray, frames: int, _time_info: Any, status: Any) -> None:
        if status:
            log.debug("Audio stream status: %s", status)
        if self._samples < self._max_samples:
            self._chunks.append(indata[:, 0].copy())
            self._samples += frames

    def stop(self) -> np.ndarray:
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks)
            self._chunks = []
            return audio
