"""WS1 evidence-completeness: every lifecycle transition — including the
failure path — emits audit + metering against the real broker state machine.

Unlike test_broker_lifecycle (which stubs audit/metering to focus on the OSB
state machine), this SPIES on them: only the external control-plane render and
the policy/quota gates are stubbed, so the audit + metering emission is the
real code path.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from moto import mock_aws


class _Captures:
    def __init__(self) -> None:
        self.audit: list[tuple[str, str]] = []
        self.metering: list[dict[str, Any]] = []


@pytest.fixture
def broker_and_captures(broker_module: Any, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from sovereign.models import PolicyDecision
    from sovereign.quotas.models import QuotaCheckResult

    caps = _Captures()
    fail_for: set[str] = set()

    async def fake_render(instance: Any) -> dict[str, Any]:
        if instance.instance_id in fail_for:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="control plane unavailable (injected)",
            )
        return {"bucket": "b", "key": f"instances/{instance.instance_id}/v1/envoy.yaml", "version": 1}

    class SpyAudit:
        def emit(self, action: str, resource: str, *_a: Any, **_k: Any) -> None:
            caps.audit.append((action, resource))

    class SpyMetering:
        def record(self, **kw: Any) -> None:
            caps.metering.append(kw)

    class AllowPolicy:
        def evaluate(self, _input: Any) -> Any:
            return PolicyDecision(allow=True, denies=[], matched_layers=[])

    class AllowQuotas:
        def check_provision(self, **_kw: Any) -> QuotaCheckResult:
            return QuotaCheckResult(allow=True)

        def usage_summary(self, _tid: str) -> list[Any]:
            return []

    monkeypatch.setattr(broker_module, "render", fake_render)
    monkeypatch.setattr(broker_module, "audit", SpyAudit())
    monkeypatch.setattr(broker_module, "metering", SpyMetering())
    monkeypatch.setattr(broker_module, "policy", AllowPolicy())
    monkeypatch.setattr(broker_module, "quotas", AllowQuotas())
    return broker_module, caps, fail_for


def _body() -> dict[str, Any]:
    return {
        "service_id": "sovereign-envoy-lb",
        "plan_id": "standard-regional",
        "organization_guid": "demo-org",
        "parameters": {
            "listeners": [{"name": "http", "port": 8080}],
            "routes": [{"host": "app.local", "prefix": "/", "cluster": "app"}],
            "clusters": [{"name": "app", "endpoints": ["127.0.0.1:3000"]}],
        },
    }


_CREDS = ("broker", "broker")


@mock_aws
def test_success_lifecycle_emits_complete_evidence(broker_and_captures: Any) -> None:
    broker_module, caps, _ = broker_and_captures
    iid = "evidence-1"
    # Context-manager form runs the broker lifespan, which creates the tables.
    with TestClient(broker_module.app) as client:
        assert client.put(
            f"/v2/service_instances/{iid}", json=_body(), auth=_CREDS
        ).status_code == 201
        assert client.patch(
            f"/v2/service_instances/{iid}", json=_body(), auth=_CREDS
        ).status_code == 200
        assert client.delete(f"/v2/service_instances/{iid}", auth=_CREDS).status_code == 200

    actions = [a for a, _ in caps.audit]
    assert "instance.provisioned" in actions
    assert "instance.updated" in actions
    assert "instance.deprovisioned" in actions
    # Metering recorded the provision (the evidence the quota path later reads).
    assert any(m.get("resource_id") == iid for m in caps.metering)


@mock_aws
def test_failed_provision_is_audited(broker_and_captures: Any) -> None:
    """The render-failure path must leave audit evidence — previously only the
    async path emitted it, so a synchronous failure went unrecorded."""
    broker_module, caps, fail_for = broker_and_captures
    iid = "evidence-fail"
    fail_for.add(iid)

    with TestClient(broker_module.app) as client:
        r = client.put(f"/v2/service_instances/{iid}", json=_body(), auth=_CREDS)
    assert r.status_code >= 500
    assert ("instance.provision_failed", iid) in caps.audit
