"""Tests for the s2t.app.App dictation state machine.

App is constructed for real (it wires up cheap objects and never starts threads or
opens hardware on its own), then the recorder / transcriber / formatter are swapped
for mocks. threading.Thread is faked so the pipeline can be driven synchronously, and
injector.insert_text / HISTORY_PATH / config writes are redirected.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import numpy as np
import pytest

from s2t import app as app_mod
from s2t import config as config_mod
from s2t.app import App, IDLE, PROCESSING, RECORDING
from s2t.audio import SAMPLE_RATE


class FakeThread:
    """Records target/args; start() is a no-op so nothing runs off-thread."""

    instances: list["FakeThread"] = []

    def __init__(self, target=None, args=(), name=None, daemon=None, **_kw):
        self.target = target
        self.args = args
        FakeThread.instances.append(self)

    def start(self) -> None:
        pass


@pytest.fixture
def app(cfg, tmp_path, monkeypatch):
    cfg["sound_cues"] = False  # no winsound.Beep
    FakeThread.instances = []
    monkeypatch.setattr(app_mod.threading, "Thread", FakeThread)
    monkeypatch.setattr(app_mod, "HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")

    a = App(cfg)
    a._recorder = MagicMock()
    a._recorder.recording = False
    a._transcriber = MagicMock()
    a._formatter = MagicMock()
    return a


# --- recording transitions -------------------------------------------------

def test_begins_idle(app) -> None:
    assert app.state == IDLE


def test_begin_recording_enters_recording_state(app) -> None:
    app._begin_recording()
    assert app.state == RECORDING
    app._recorder.start.assert_called_once()


def test_begin_recording_ignored_when_disabled(app) -> None:
    app.enabled = False
    app._begin_recording()
    assert app.state == IDLE
    app._recorder.start.assert_not_called()


def test_begin_recording_ignored_when_already_recording(app) -> None:
    app._begin_recording()
    app._recorder.start.reset_mock()
    app._begin_recording()  # second press while recording
    app._recorder.start.assert_not_called()


def test_begin_recording_recovers_when_mic_fails(app) -> None:
    app._recorder.start.side_effect = RuntimeError("mic in use")
    app._begin_recording()
    assert app.state == IDLE  # rolled back, not stuck in RECORDING


def test_finish_recording_moves_to_processing_and_spawns_pipeline(app) -> None:
    app._begin_recording()
    app._recorder.stop.return_value = np.ones(SAMPLE_RATE, dtype=np.float32)
    app._finish_recording()
    assert app.state == PROCESSING
    app._recorder.stop.assert_called_once()
    # the pipeline was handed to a (fake) background thread
    assert any(t.target == app._process for t in FakeThread.instances)


def test_finish_recording_ignored_when_not_recording(app) -> None:
    app._finish_recording()  # still idle
    assert app.state == IDLE
    app._recorder.stop.assert_not_called()


def test_toggle_starts_then_stops(app) -> None:
    app._toggle()
    assert app.state == RECORDING
    app._recorder.stop.return_value = np.ones(SAMPLE_RATE, dtype=np.float32)
    app._toggle()
    assert app.state == PROCESSING


# --- the processing pipeline ----------------------------------------------

def test_process_transcribes_cleans_inserts_and_logs(app, monkeypatch) -> None:
    inserted: dict = {}
    monkeypatch.setattr(app_mod.injector, "insert_text",
                        lambda text, mode, restore_clipboard: inserted.update(
                            text=text, mode=mode))
    app._transcriber.transcribe.return_value = "um hello world"
    app._formatter.clean.return_value = "Hello world."

    app._process(np.ones(SAMPLE_RATE, dtype=np.float32))

    assert inserted["text"] == "Hello world."
    assert inserted["mode"] == "paste"
    assert app.state == IDLE
    # one history line, with both raw and cleaned text
    line = (app_mod.HISTORY_PATH).read_text(encoding="utf-8").strip()
    entry = json.loads(line)
    assert entry["raw"] == "um hello world"
    assert entry["text"] == "Hello world."


def test_process_skips_too_short_audio(app, monkeypatch) -> None:
    called = MagicMock()
    monkeypatch.setattr(app_mod.injector, "insert_text", called)
    app._process(np.ones(100, dtype=np.float32))  # far under MIN_AUDIO_SECONDS
    app._transcriber.transcribe.assert_not_called()
    called.assert_not_called()
    assert app.state == IDLE


def test_process_skips_when_no_speech_detected(app, monkeypatch) -> None:
    called = MagicMock()
    monkeypatch.setattr(app_mod.injector, "insert_text", called)
    app._transcriber.transcribe.return_value = ""  # silence
    app._process(np.ones(SAMPLE_RATE, dtype=np.float32))
    app._formatter.clean.assert_not_called()
    called.assert_not_called()
    assert app.state == IDLE


def test_process_recovers_from_pipeline_exception(app, monkeypatch) -> None:
    monkeypatch.setattr(app_mod.injector, "insert_text", MagicMock())
    app._transcriber.transcribe.side_effect = RuntimeError("whisper blew up")
    app._process(np.ones(SAMPLE_RATE, dtype=np.float32))
    assert app.state == IDLE  # finally-block always resets the machine


# --- enable / disable ------------------------------------------------------

def test_set_enabled_false_stops_active_recording(app) -> None:
    app._begin_recording()
    assert app.state == RECORDING
    app.set_enabled(False)
    assert app.enabled is False
    assert app.state == IDLE
    app._recorder.stop.assert_called_once()


# --- mic + model setters ---------------------------------------------------

def test_set_mic_device_persists_and_rebuilds_recorder(app) -> None:
    old_recorder = app._recorder
    app.set_mic_device(3)
    assert app.current_mic() == 3
    assert app._recorder is not old_recorder  # a new Recorder for the new device
    assert json.loads(config_mod.CONFIG_PATH.read_text(encoding="utf-8"))["mic_device"] == 3


def test_set_mic_device_noop_when_unchanged(app) -> None:
    old_recorder = app._recorder
    app.set_mic_device(app.current_mic())  # same value
    assert app._recorder is old_recorder


def test_set_lmstudio_model_updates_config(app) -> None:
    app.set_lmstudio_model("some/other-model")
    assert app.current_model() == "some/other-model"
    saved = json.loads(config_mod.CONFIG_PATH.read_text(encoding="utf-8"))
    assert saved["lmstudio"]["model"] == "some/other-model"


def test_set_lmstudio_model_noop_when_empty(app) -> None:
    before = app.current_model()
    app.set_lmstudio_model("")
    assert app.current_model() == before


def test_current_hotkeys_reports_both_bindings(app) -> None:
    hk = app.current_hotkeys()
    assert set(hk) == {"hold", "toggle"}
