"""W3C trace-context propagation + log correlation (E5).

Dependency-free: enough to give every request a trace id that flows across
services via the `traceparent` header and onto structured log lines, so a
request can be followed end-to-end. Not a full tracer — no span export — but
the wire format is W3C `traceparent`, so a real OTel collector can be dropped
in later without changing the contract.
"""

from __future__ import annotations

import re
import secrets
from contextvars import ContextVar

#: The id of the request currently being handled, for log correlation.
current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)

# version "00", 16-byte trace-id, 8-byte parent-id, 1-byte flags — all hex.
_TRACEPARENT_RE = re.compile(
    r"^00-(?P<trace>[0-9a-f]{32})-(?P<span>[0-9a-f]{16})-[0-9a-f]{2}$"
)
_ZERO_TRACE = "0" * 32
_ZERO_SPAN = "0" * 16


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """Return (trace_id, parent_span_id) from a valid `traceparent`, else
    None. All-zero ids are rejected per the W3C spec."""
    if not header:
        return None
    match = _TRACEPARENT_RE.match(header.strip())
    if not match:
        return None
    trace, span = match.group("trace"), match.group("span")
    if trace == _ZERO_TRACE or span == _ZERO_SPAN:
        return None
    return trace, span


def format_traceparent(trace_id: str, span_id: str, *, sampled: bool = True) -> str:
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"
