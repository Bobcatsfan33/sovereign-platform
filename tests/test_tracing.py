"""Tests for W3C trace-context parsing/formatting (E5)."""

from __future__ import annotations

import pytest
from sovereign.tracing import (
    format_traceparent,
    new_span_id,
    new_trace_id,
    parse_traceparent,
)


def test_parse_valid_traceparent() -> None:
    tp = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    assert parse_traceparent(tp) == ("a" * 32, "b" * 16)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "garbage",
        "00-tooshort-bbbbbbbbbbbbbbbb-01",
        "ff-" + "a" * 32 + "-" + "b" * 16 + "-01",  # wrong version
        "00-" + "0" * 32 + "-" + "b" * 16 + "-01",  # all-zero trace
        "00-" + "a" * 32 + "-" + "0" * 16 + "-01",  # all-zero span
    ],
)
def test_parse_rejects_invalid(header: str | None) -> None:
    assert parse_traceparent(header) is None


def test_format_round_trips() -> None:
    trace, span = new_trace_id(), new_span_id()
    assert parse_traceparent(format_traceparent(trace, span)) == (trace, span)
    assert format_traceparent(trace, span, sampled=False).endswith("-00")


def test_new_ids_have_correct_length() -> None:
    assert len(new_trace_id()) == 32
    assert len(new_span_id()) == 16
