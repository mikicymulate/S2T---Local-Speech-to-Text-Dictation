"""Tests for s2t.transcriber: empty-audio short-circuit and segment assembly.

faster-whisper is never loaded; a preset fake model is injected so the loading branch
in transcribe() is skipped and only the text-joining logic is exercised.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import numpy as np

from s2t.config import DEFAULTS
from s2t.transcriber import Transcriber


def make_transcriber() -> Transcriber:
    return Transcriber(copy.deepcopy(DEFAULTS["whisper"]))


def test_transcribe_empty_audio_returns_empty_without_loading() -> None:
    t = make_transcriber()
    # _model stays None: if load() were called it would try to import faster-whisper
    assert t.transcribe(np.zeros(0, dtype=np.float32)) == ""
    assert t._model is None


def test_transcribe_joins_and_strips_segments() -> None:
    t = make_transcriber()
    segments = [SimpleNamespace(text="  Hello  "), SimpleNamespace(text=" world. ")]
    info = SimpleNamespace(language="en")
    t._model = SimpleNamespace(transcribe=lambda *a, **k: (segments, info))

    assert t.transcribe(np.ones(16000, dtype=np.float32)) == "Hello world."


def test_transcribe_passes_configured_language(monkeypatch) -> None:
    t = make_transcriber()
    t._cfg["language"] = "fr"
    captured: dict = {}

    def fake_transcribe(audio, **kwargs):
        captured.update(kwargs)
        return ([SimpleNamespace(text="bonjour")], SimpleNamespace(language="fr"))

    t._model = SimpleNamespace(transcribe=fake_transcribe)
    t.transcribe(np.ones(16000, dtype=np.float32))
    assert captured["language"] == "fr"
    assert captured["vad_filter"] is True
