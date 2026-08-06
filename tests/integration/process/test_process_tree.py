from __future__ import annotations

from coding_agent_harness.adapters.process import runner as process_runner
from coding_agent_harness.adapters.process.runner import BoundedCapture, SubprocessLauncher


def test_stdout_and_stderr_are_bounded_during_collection_and_keep_head_tail() -> None:
    capture = BoundedCapture(limit=16)
    capture.feed(b"abcdefghij")
    capture.feed(b"klmnopqrst")
    assert capture.truncated is True
    assert len(capture.value) == 16
    assert capture.value.startswith(b"abcdefgh")
    assert capture.value.endswith(b"mnopqrst")


def test_stream_collectors_have_independent_limits() -> None:
    stdout = BoundedCapture(limit=8)
    stderr = BoundedCapture(limit=8)
    stdout.feed(b"a" * 20)
    stderr.feed(b"b" * 20)
    assert stdout.value == b"a" * 8
    assert stderr.value == b"b" * 8
    assert stdout.truncated and stderr.truncated


def test_windows_timeout_terminates_the_process_tree_without_shell(monkeypatch) -> None:
    calls = []

    class Process:
        pid = 42
        def wait(self, timeout):
            calls.append(("wait", timeout))
        def kill(self):
            raise AssertionError("fallback kill was not expected")

    monkeypatch.setattr(process_runner.os, "name", "nt")
    monkeypatch.setattr(process_runner.subprocess, "run", lambda argv, **kwargs: calls.append((tuple(argv), kwargs)))
    SubprocessLauncher._terminate_tree(Process())
    assert calls[0][0] == ("taskkill", "/PID", "42", "/T", "/F")
    assert calls[0][1]["check"] is False
    assert calls[1] == ("wait", 5)
