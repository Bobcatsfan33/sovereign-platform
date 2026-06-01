"""Tests for the durable audit disk spool (S5 hardening)."""

from __future__ import annotations

from pathlib import Path

from sovereign.audit_spool import AuditSpool
from sovereign.models import AuditEvent


def _event(action: str = "test.event", resource: str = "svc/x") -> AuditEvent:
    return AuditEvent(action=action, resource=resource, tenant_id="acme")


def test_append_and_drain_round_trip(tmp_path: Path) -> None:
    spool = AuditSpool(tmp_path / "audit.spool")
    assert spool.append(_event("a")) is True
    assert spool.append(_event("b")) is True
    assert spool.count() == 2

    drained = spool.drain()
    assert [e.action for e in drained] == ["a", "b"]
    # Drain clears the spool.
    assert spool.count() == 0
    assert spool.drain() == []


def test_drain_missing_spool_is_empty(tmp_path: Path) -> None:
    spool = AuditSpool(tmp_path / "nope.spool")
    assert spool.drain() == []
    assert spool.count() == 0


def test_size_cap_refuses_append(tmp_path: Path) -> None:
    spool = AuditSpool(tmp_path / "audit.spool", max_bytes=1)
    # First write creates the file; subsequent writes see size >= cap.
    spool.append(_event("first"))
    assert spool.append(_event("second")) is False


def test_torn_final_line_is_skipped(tmp_path: Path) -> None:
    p = tmp_path / "audit.spool"
    spool = AuditSpool(p)
    spool.append(_event("good"))
    # Simulate a crash mid-write: append a partial JSON line.
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"action": "torn", "reso')
    drained = spool.drain()
    assert [e.action for e in drained] == ["good"]


def test_event_fields_survive_round_trip(tmp_path: Path) -> None:
    spool = AuditSpool(tmp_path / "audit.spool")
    ev = AuditEvent(
        action="policy.evaluated",
        resource="provision:i1",
        tenant_id="cade2",
        actor="alice@gov",
        decision="deny",
        metadata={"denies": ["SC-8: TLS required"]},
    )
    spool.append(ev)
    (got,) = spool.drain()
    assert got.tenant_id == "cade2"
    assert got.decision == "deny"
    assert got.metadata["denies"] == ["SC-8: TLS required"]
