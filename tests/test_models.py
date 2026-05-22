"""Unit tests for the shared Pydantic governance models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sovereign.models import (
    AuditEvent,
    Binding,
    Cluster,
    InstanceStatus,
    LbParameters,
    PolicyDecision,
    PolicyRequest,
    ProvisionRequest,
    ServiceInstance,
    Usage,
)


class TestAuditEvent:
    def test_defaults(self) -> None:
        e = AuditEvent(action="provision", resource="svc/demo")
        assert e.tenant_id == "default"
        assert e.actor == "system"
        assert e.decision == "allow"
        assert e.metadata == {}
        assert isinstance(e.ts, datetime)
        # ts is timezone-aware
        assert e.ts.tzinfo is not None

    def test_full_payload(self) -> None:
        when = datetime(2026, 1, 1, tzinfo=timezone.utc)
        e = AuditEvent(
            ts=when,
            tenant_id="acme",
            actor="alice",
            action="policy_check",
            resource="svc/demo",
            decision="deny",
            metadata={"reason": "quota"},
        )
        round = AuditEvent.model_validate_json(e.model_dump_json())
        assert round.tenant_id == "acme"
        assert round.decision == "deny"
        assert round.metadata["reason"] == "quota"
        assert round.ts == when

    def test_action_required(self) -> None:
        with pytest.raises(ValidationError):
            AuditEvent(resource="svc/demo")  # type: ignore[call-arg]


class TestPolicyModels:
    def test_request_required_fields(self) -> None:
        r = PolicyRequest(tenant_id="t", actor="a", action="x", resource="r")
        assert r.attributes == {}

    def test_decision_defaults(self) -> None:
        d = PolicyDecision(allow=True)
        assert d.reason == ""
        assert d.obligations == []


class TestUsage:
    def test_quantity_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            Usage(tenant_id="t", resource_id="r", resource_type="cpu", quantity=-1, unit="s")

    def test_round_trip(self) -> None:
        u = Usage(
            tenant_id="acme",
            resource_id="demo-lb",
            resource_type="lb-hour",
            quantity=2.5,
            unit="hour",
            metadata={"region": "us-east-1"},
        )
        decoded = Usage.model_validate_json(u.model_dump_json())
        assert decoded.quantity == 2.5
        assert decoded.metadata["region"] == "us-east-1"


class TestOSBModels:
    def test_provision_request_defaults(self) -> None:
        r = ProvisionRequest(service_id="s", plan_id="p")
        assert isinstance(r.parameters, LbParameters)
        # default LbParameters has one HTTP listener on 8080
        assert r.parameters.listeners[0].port == 8080

    def test_cluster_must_have_endpoints(self) -> None:
        with pytest.raises(ValidationError, match="at least one endpoint"):
            Cluster(name="c", endpoints=[])

    def test_listener_port_bounds(self) -> None:
        from sovereign.models import Listener

        with pytest.raises(ValidationError):
            Listener(name="x", port=0)
        with pytest.raises(ValidationError):
            Listener(name="x", port=70000)

    def test_service_instance_status_default(self) -> None:
        req = ProvisionRequest(service_id="s", plan_id="p")
        inst = ServiceInstance(instance_id="i", **req.model_dump())
        assert inst.status == InstanceStatus.provisioning
        assert inst.version == 1

    def test_binding_round_trip(self) -> None:
        b = Binding(binding_id="b", instance_id="i", credentials={"url": "http://x"})
        assert b.credentials["url"] == "http://x"
