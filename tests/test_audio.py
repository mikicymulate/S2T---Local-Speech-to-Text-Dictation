"""Tests for s2t.audio: device resolution, enumeration, and the Recorder buffer.

sounddevice is never asked to open a real stream; only its query_devices() is patched.
"""

from __future__ import annotations

import numpy as np
import pytest

from s2t import audio


FAKE_DEVICES = [
    {"name": "Microphone (USB Audio)", "max_input_channels": 2},
    {"name": "Speakers (Realtek)", "max_input_channels": 0},
    {"name": "Line In", "max_input_channels": 1},
]


# --- resolve_device --------------------------------------------------------

def test_resolve_device_none_is_default() -> None:
    assert audio.resolve_device(None) is None


def test_resolve_device_empty_string_is_default() -> None:
    assert audio.resolve_device("") is None


def test_resolve_device_passes_through_int_index() -> None:
    assert audio.resolve_device(7) == 7


def test_resolve_device_matches_name_substring(monkeypatch) -> None:
    monkeypatch.setattr(audio.sd, "query_devices", lambda: FAKE_DEVICES)
    assert audio.resolve_device("usb audio") == 0
    assert audio.resolve_device("line in") == 2


def test_resolve_device_ignores_output_only_devices(monkeypatch) -> None:
    monkeypatch.setattr(audio.sd, "query_devices", lambda: FAKE_DEVICES)
    # "Realtek" is an output device (0 input channels): no match -> default
    assert audio.resolve_device("realtek") is None


def test_resolve_device_unknown_name_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setattr(audio.sd, "query_devices", lambda: FAKE_DEVICES)
    assert audio.resolve_device("nonexistent mic") is None


# --- list_input_devices ----------------------------------------------------

def test_list_input_devices_returns_only_capture_devices(monkeypatch) -> None:
    monkeypatch.setattr(audio.sd, "query_devices", lambda: FAKE_DEVICES)
    assert audio.list_input_devices() == [(0, "Microphone (USB Audio)"), (2, "Line In")]


def test_list_input_devices_swallows_errors(monkeypatch) -> None:
    def boom():
        raise RuntimeError("no audio backend")

    monkeypatch.setattr(audio.sd, "query_devices", boom)
    assert audio.list_input_devices() == []


# --- Recorder buffer logic (no real stream) --------------------------------

def test_recorder_starts_not_recording() -> None:
    rec = audio.Recorder(mic_device=None, max_seconds=5)
    assert rec.recording is False


def test_recorder_stop_without_start_returns_empty() -> None:
    rec = audio.Recorder(mic_device=None, max_seconds=5)
    out = rec.stop()
    assert out.size == 0
    assert out.dtype == np.float32


def test_recorder_callback_accumulates_samples() -> None:
    rec = audio.Recorder(mic_device=None, max_seconds=5)
    frame = np.ones((100, 1), dtype=np.float32)
    rec._callback(frame, 100, None, None)
    rec._callback(frame, 100, None, None)
    assert rec._samples == 200
    assert len(rec._chunks) == 2


def test_recorder_callback_respects_max_samples_cap() -> None:
    # max_seconds tiny so _max_samples is small; extra audio past the cap is dropped
    rec = audio.Recorder(mic_device=None, max_seconds=0.01)  # 160 samples at 16 kHz
    frame = np.ones((160, 1), dtype=np.float32)
    rec._callback(frame, 160, None, None)   # fills to the cap
    rec._callback(frame, 160, None, None)   # over cap: ignored
    assert rec._samples == 160
    assert len(rec._chunks) == 1


# --- MicLevelMonitor level maths -------------------------------------------

def test_mic_level_monitor_updates_level_from_rms() -> None:
    mon = audio.MicLevelMonitor(device=None)
    frame = np.full((256, 1), 0.05, dtype=np.float32)  # RMS 0.05
    mon._callback(frame, 256, None, None)
    # level = min(1.0, max(prev*0.6, rms*8)) = 0.05 * 8 = 0.4
    assert mon.level == pytest.approx(0.4, abs=1e-6)


def test_mic_level_monitor_level_is_clamped_to_one() -> None:
    mon = audio.MicLevelMonitor(device=None)
    frame = np.ones((256, 1), dtype=np.float32)  # RMS 1.0 -> 8.0 before clamp
    mon._callback(frame, 256, None, None)
    assert mon.level == 1.0
