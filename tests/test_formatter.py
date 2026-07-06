"""Tests for s2t.formatter: prompt building, streaming cleanup + fallbacks, model listing.

No real LM Studio server or OpenAI client is used: Formatter._client is replaced with a
fake, and subprocess/requests are patched.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from s2t import formatter as fmt
from s2t.config import DEFAULTS
from tests.conftest import FakeStream, make_chunk


def make_formatter(dictionary: dict[str, str] | None = None) -> fmt.Formatter:
    lm_cfg = copy.deepcopy(DEFAULTS["lmstudio"])
    return fmt.Formatter(lm_cfg, dictionary or {})


def with_stream(f: fmt.Formatter, chunks: list) -> FakeStream:
    """Wire a fake OpenAI client onto the formatter so clean() streams `chunks`."""
    stream = FakeStream(chunks)
    client = MagicMock()
    client.chat.completions.create.return_value = stream
    f._client = client
    return stream


# --- _prompt ---------------------------------------------------------------

def test_prompt_without_dictionary_has_no_dictionary_clause() -> None:
    prompt = make_formatter()._prompt("hello world")
    assert prompt.startswith("/no_think")
    assert "hello world" in prompt
    assert "vocabulary corrections" not in prompt


def test_prompt_with_dictionary_includes_corrections() -> None:
    prompt = make_formatter({"gemma": "Gemma"})._prompt("gemma is fast")
    assert "vocabulary corrections" in prompt
    assert '"gemma" means "Gemma"' in prompt


# --- clean: short-circuits -------------------------------------------------

def test_clean_returns_raw_when_disabled() -> None:
    f = make_formatter()
    f._cfg["enabled"] = False
    assert f.clean("um hello") == "um hello"


def test_clean_returns_raw_for_blank_input() -> None:
    f = make_formatter()
    # a client that would explode if called proves the network is never touched
    f._client = MagicMock(side_effect=AssertionError("must not be called"))
    assert f.clean("   ") == "   "


# --- clean: streaming ------------------------------------------------------

def test_clean_assembles_streamed_chunks_and_strips() -> None:
    f = make_formatter()
    with_stream(f, [make_chunk("Hello "), make_chunk(None), make_chunk("world.")])
    assert f.clean("hello world") == "Hello world."


def test_clean_strips_wrapping_quotes() -> None:
    f = make_formatter()
    with_stream(f, [make_chunk('"Hello world."')])
    assert f.clean("hello world") == "Hello world."


def test_clean_strips_wrapping_single_quotes() -> None:
    f = make_formatter()
    with_stream(f, [make_chunk("'Hello world.'")])
    assert f.clean("hello world") == "Hello world."


def test_clean_strips_wrapping_smart_quotes() -> None:
    # models sometimes return curly-quoted text: “...” (open U+201C, close U+201D)
    f = make_formatter()
    with_stream(f, [make_chunk("“Hello world.”")])
    assert f.clean("hello world") == "Hello world."


def test_clean_keeps_internal_and_unbalanced_quotes() -> None:
    f = make_formatter()
    with_stream(f, [make_chunk('He said "hi".')])
    assert f.clean("he said hi") == 'He said "hi".'


def test_clean_falls_back_to_raw_on_empty_response() -> None:
    f = make_formatter()
    with_stream(f, [make_chunk("   ")])
    assert f.clean("hello world") == "hello world"


def test_clean_falls_back_to_raw_on_exception() -> None:
    f = make_formatter()
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("server down")
    f._client = client
    assert f.clean("hello world") == "hello world"


def test_clean_times_out_and_closes_stream(monkeypatch) -> None:
    f = make_formatter()
    stream = with_stream(f, [make_chunk("late text")])
    # first monotonic() sets the deadline (0 + timeout); the in-loop check reads far past it
    times = iter([0.0, 10_000.0])
    monkeypatch.setattr(fmt.time, "monotonic", lambda: next(times))

    assert f.clean("hello world") == "hello world"
    assert stream.closed is True  # streaming request cancelled server-side


# --- list_models -----------------------------------------------------------

def test_list_models_keeps_only_llms_from_lms(monkeypatch) -> None:
    payload = [
        {"type": "llm", "modelKey": "google/gemma-4-e4b", "displayName": "Gemma 4"},
        {"type": "embedding", "modelKey": "nomic-embed", "displayName": "Nomic"},
    ]
    monkeypatch.setattr(
        fmt.subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)),
    )
    lm_cfg = copy.deepcopy(DEFAULTS["lmstudio"])
    models = fmt.list_models(lm_cfg)
    assert ("google/gemma-4-e4b", "Gemma 4") in models
    assert all("nomic-embed" != key for key, _ in models)


def test_list_models_prepends_current_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(
        fmt.subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout="[]"),
    )
    # /models fallback also returns nothing
    monkeypatch.setattr(fmt.requests, "get",
                        lambda *a, **k: SimpleNamespace(json=lambda: {"data": []}))
    lm_cfg = copy.deepcopy(DEFAULTS["lmstudio"])
    models = fmt.list_models(lm_cfg)
    assert models[0] == (lm_cfg["model"], lm_cfg["model"])


def test_list_models_falls_back_to_models_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        fmt.subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout="[]"),
    )
    resp = SimpleNamespace(json=lambda: {"data": [{"id": "some/model"},
                                                  {"id": "text-embed-3"}]})
    monkeypatch.setattr(fmt.requests, "get", lambda *a, **k: resp)
    lm_cfg = copy.deepcopy(DEFAULTS["lmstudio"])
    keys = {key for key, _ in fmt.list_models(lm_cfg)}
    assert "some/model" in keys
    assert "text-embed-3" not in keys  # embeddings filtered out


# --- server_reachable ------------------------------------------------------

def test_server_reachable_true(monkeypatch) -> None:
    f = make_formatter()
    monkeypatch.setattr(fmt.requests, "get", lambda *a, **k: SimpleNamespace())
    assert f.server_reachable() is True


def test_server_reachable_false_on_connection_error(monkeypatch) -> None:
    f = make_formatter()

    def boom(*_a, **_k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(fmt.requests, "get", boom)
    assert f.server_reachable() is False
