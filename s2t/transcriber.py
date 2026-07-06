"""Local speech-to-text via faster-whisper (CTranslate2). Model is lazy-loaded on first use."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

from .config import WhisperConfig

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, whisper_cfg: WhisperConfig):
        self._cfg = whisper_cfg
        self._model: WhisperModel | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model (downloads it from Hugging Face on the very first run)."""
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel  # slow import, keep it here

            log.info(
                "Loading Whisper model %r (%s/%s)...",
                self._cfg["model"], self._cfg["device"], self._cfg["compute_type"],
            )
            self._model = WhisperModel(
                self._cfg["model"],
                device=self._cfg["device"],
                compute_type=self._cfg["compute_type"],
            )
            log.info("Whisper model ready")

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
        self.load()
        assert self._model is not None  # load() guarantees it
        segments, info = self._model.transcribe(
            audio,
            language=self._cfg.get("language") or None,
            vad_filter=True,
            beam_size=5,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("Transcribed %.1fs of audio (lang=%s): %r", audio.size / 16000, info.language, text)
        return text
