"""Microphone capture: 16 kHz mono float32, buffered in memory between start() and stop()."""

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what Whisper expects


def resolve_device(mic_device):
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


class Recorder:
    def __init__(self, mic_device=None, max_seconds=300):
        self._device = resolve_device(mic_device)
        self._max_samples = int(max_seconds * SAMPLE_RATE)
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self):
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

    def _callback(self, indata, frames, time_info, status):
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
