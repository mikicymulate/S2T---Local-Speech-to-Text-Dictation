"""Shared pytest fixtures and helpers for the S2T test suite.

The tests never touch real hardware (mic), the network (LM Studio), the global
keyboard hook, or the user's real config/history files. External boundaries are
mocked and the module-level CONFIG_PATH / HISTORY_PATH constants are redirected
to a tmp dir wherever a test exercises code that writes them.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

import pytest

from s2t.config import DEFAULTS, Config


@pytest.fixture
def cfg() -> Config:
    """A fresh, independent copy of the default config for each test."""
    return copy.deepcopy(DEFAULTS)


def make_chunk(content: str | None) -> SimpleNamespace:
    """A minimal stand-in for an OpenAI streaming chunk: chunk.choices[0].delta.content."""
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class FakeStream:
    """Iterable stand-in for the object returned by chat.completions.create(stream=True).

    Records whether close() was called so tests can assert the streaming request is
    cancelled server-side on timeout.
    """

    def __init__(self, chunks: list[Any]):
        self._chunks = chunks
        self.closed = False

    def __iter__(self) -> Any:
        return iter(self._chunks)

    def close(self) -> None:
        self.closed = True
