"""WS3: the trace propagates across the provisioning path — every inter-service
call and every executor subprocess carries the request's trace id."""

from __future__ import annotations

from typing import Any

import pytest
from sovereign.tracing import (
    current_trace_id,
    outbound_trace_headers,
    parse_traceparent,
    subprocess_trace_env,
)

_TRACE = "a" * 32


def test_outbound_headers_carry_the_current_trace() -> None:
    token = current_trace_id.set(_TRACE)
    try:
        tp = outbound_trace_headers()["traceparent"]
        parsed = parse_traceparent(tp)
        assert parsed is not None and parsed[0] == _TRACE  # same trace, new span
    finally:
        current_trace_id.reset(token)


def test_outbound_headers_start_a_trace_outside_a_request() -> None:
    # No current_trace_id set (background task) -> a fresh, valid trace.
    assert parse_traceparent(outbound_trace_headers()["traceparent"]) is not None


def test_service_auth_headers_propagate_trace() -> None:
    from sovereign.security import service_auth_headers

    token = current_trace_id.set(_TRACE)
    try:
        headers = service_auth_headers()
        assert parse_traceparent(headers["traceparent"])[0] == _TRACE  # type: ignore[index]
    finally:
        current_trace_id.reset(token)


def test_subprocess_env_carries_trace() -> None:
    token = current_trace_id.set(_TRACE)
    try:
        env = subprocess_trace_env()
        assert parse_traceparent(env["TRACEPARENT"])[0] == _TRACE  # type: ignore[index]
    finally:
        current_trace_id.reset(token)


def test_executor_run_injects_traceparent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shell executor must pass TRACEPARENT into the apply subprocess."""
    from sovereign.executors import shell

    captured: dict[str, Any] = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd: list[str], **kwargs: Any) -> _Proc:
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr(shell.subprocess, "run", fake_run)
    token = current_trace_id.set(_TRACE)
    try:
        shell._run(["terraform", "version"])
    finally:
        current_trace_id.reset(token)

    assert "TRACEPARENT" in captured["env"]
    assert parse_traceparent(captured["env"]["TRACEPARENT"])[0] == _TRACE  # type: ignore[index]
