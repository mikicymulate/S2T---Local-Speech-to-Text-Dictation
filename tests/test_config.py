"""Tests for s2t.config: schema defaults, deep merge, and load/save round-trips."""

from __future__ import annotations

import json

import pytest

from s2t import config
from s2t.config import Config, DEFAULTS


# --- _merge ----------------------------------------------------------------

def test_merge_overrides_scalar() -> None:
    out = config._merge({"a": 1, "b": 2}, {"b": 3})
    assert out == {"a": 1, "b": 3}


def test_merge_recurses_into_nested_dicts() -> None:
    base = {"whisper": {"model": "small", "language": None}}
    override = {"whisper": {"model": "medium"}}
    out = config._merge(base, override)
    # the untouched nested key survives the merge
    assert out == {"whisper": {"model": "medium", "language": None}}


def test_merge_adds_new_keys() -> None:
    out = config._merge({"a": 1}, {"b": 2})
    assert out == {"a": 1, "b": 2}


def test_merge_does_not_mutate_base() -> None:
    base = {"whisper": {"model": "small"}}
    config._merge(base, {"whisper": {"model": "large"}})
    assert base == {"whisper": {"model": "small"}}


def test_merge_replaces_dict_with_scalar_when_override_is_scalar() -> None:
    # a malformed user value (scalar over a dict) just replaces it, no crash
    out = config._merge({"whisper": {"model": "small"}}, {"whisper": "oops"})
    assert out == {"whisper": "oops"}


# --- load_config -----------------------------------------------------------

def test_load_config_creates_default_file_when_missing(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    assert not path.exists()

    loaded = config.load_config()

    assert path.exists()
    assert loaded == DEFAULTS
    # the file written to disk is the defaults, verbatim
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULTS


def test_load_config_merges_partial_user_config_over_defaults(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"whisper": {"model": "medium"}, "sound_cues": False}),
                    encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    loaded = config.load_config()

    assert loaded["whisper"]["model"] == "medium"      # user override applied
    assert loaded["whisper"]["compute_type"] == "int8"  # default preserved
    assert loaded["sound_cues"] is False
    assert loaded["hotkeys"] == DEFAULTS["hotkeys"]      # untouched section intact


def test_load_config_returns_defaults_on_corrupt_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    loaded = config.load_config()

    assert loaded == DEFAULTS


def test_load_config_does_not_return_the_defaults_object(tmp_path, monkeypatch) -> None:
    # mutating a loaded config must never corrupt the shared DEFAULTS template
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    loaded = config.load_config()
    loaded["whisper"]["model"] = "large-v3"

    assert DEFAULTS["whisper"]["model"] == "small"


# --- save_config -----------------------------------------------------------

def test_save_config_round_trips(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    cfg: Config = config.load_config()
    cfg["max_record_seconds"] = 42
    assert config.save_config(cfg) is True

    assert config.load_config()["max_record_seconds"] == 42


def test_save_config_returns_false_on_oserror(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    cfg = config.load_config()  # creates the file while write_text still works

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(type(path), "write_text", boom)
    assert config.save_config(cfg) is False


# --- DEFAULTS shape --------------------------------------------------------

def test_defaults_have_every_config_key() -> None:
    assert set(DEFAULTS.keys()) == set(Config.__annotations__.keys())
