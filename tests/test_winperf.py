"""Tests for s2t.winperf.unthrottle_lmstudio: parsing tasklist CSV into PIDs.

The Win32 calls (_unthrottle_pid) and the tasklist subprocess are patched, so the test
only checks that PIDs are extracted correctly and that failures stay best-effort.
"""

from __future__ import annotations

from types import SimpleNamespace

from s2t import winperf


TASKLIST_CSV = (
    '"LM Studio.exe","12345","Console","1","250,000 K"\n'
    '"LM Studio.exe","6789","Console","1","64,000 K"\n'
)


def test_unthrottle_parses_all_pids(monkeypatch) -> None:
    monkeypatch.setattr(winperf.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=TASKLIST_CSV))
    seen: list[int] = []
    monkeypatch.setattr(winperf, "_unthrottle_pid",
                        lambda pid: (seen.append(pid), True)[1])

    winperf.unthrottle_lmstudio()
    assert seen == [12345, 6789]


def test_unthrottle_handles_no_matching_process(monkeypatch) -> None:
    # tasklist prints an info banner (no quoted CSV rows) when nothing matches
    monkeypatch.setattr(
        winperf.subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout='INFO: No tasks are running.\n'),
    )
    called: list[int] = []
    monkeypatch.setattr(winperf, "_unthrottle_pid",
                        lambda pid: called.append(pid) or True)

    winperf.unthrottle_lmstudio()  # must not raise
    assert called == []


def test_unthrottle_swallows_subprocess_errors(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise OSError("tasklist missing")

    monkeypatch.setattr(winperf.subprocess, "run", boom)
    # best-effort: a failure here must never propagate
    winperf.unthrottle_lmstudio()
