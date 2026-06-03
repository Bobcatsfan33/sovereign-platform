"""Broker end-to-end tests for Phase 3 — JWT RBAC, quota gate, /v2/usage,
   and per-tenant policy context lifting."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.models import PolicyDecision
from sovereign.quotas import Quota, service_type_scope
from sovereign.tenancy import (
    Role,
    RoleBinding,
    Tenant,
    TenantLevel,
    mint_dev_token,
)


def _provision_body(
    *,
    organization_guid: str | None = "cade2",
    region: str = "us-gov-west-1",
    tls: bool = True,
) -> dict[str, Any]:
    body = {
        "service_id": "sovereign-envoy-lb",
        "plan_id": "standard-regional",
        "parameters": {
            "region": region,
            "tls": tls,
            "logging_enabled": True,
            "listeners": [{"name": "http", "port": 8080, "protocol": "HTTP"}],
            "routes": [{"host": "app.local", "prefix": "/", "cluster": "app"}],
            "clusters": [{"name": "app", "endpoints": ["127.0.0.1:3000"]}],
        },
    }
    if organization_guid is not None:
        body["organization_guid"] = organization_guid
    return body


@pytest.fixture
def broker_phase3(broker_module: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Broker with REAL tenancy + quota stores (moto-backed) but stubbed
    render + audit + policy + metering so we can assert on RBAC and
    quota wiring without standing up OPA / control-plane."""

    rendered: list[str] = []

    async def fake_render(instance: Any) -> dict[str, Any]:
        rendered.append(instance.instance_id)
        return {"bucket": "b", "key": f"instances/{instance.instance_id}/v1/envoy.yaml", "version": 1}

    emitted: list[dict[str, Any]] = []

    class FakeAudit:
        def emit(self, action: str, resource: str, **kw: Any) -> None:
            emitted.append({"action": action, "resource": resource, **kw})

    monkeypatch.setattr(broker_module, "render", fake_render)
    monkeypatch.setattr(broker_module, "audit", FakeAudit())

    # Capture policy inputs so tests can assert on tenant context lifting.
    seen_policy_inputs: list[dict[str, Any]] = []

    class CapturingPolicy:
        def evaluate(self, policy_input: dict[str, Any]) -> PolicyDecision:
            seen_policy_inputs.append(policy_input)
            return PolicyDecision(allow=True, denies=[], matched_layers=[])

    monkeypatch.setattr(broker_module, "policy", CapturingPolicy())

    class FakeMetering:
        def record(self, **_kw: Any) -> None:
            return None

    monkeypatch.setattr(broker_module, "metering", FakeMetering())

    broker_module._test_emitted = emitted  # type: ignore[attr-defined]
    broker_module._test_rendered = rendered  # type: ignore[attr-defined]
    broker_module._test_policy_inputs = seen_policy_inputs  # type: ignore[attr-defined]
    return broker_module


def _seed_tree(broker_module: Any) -> None:
    """Standard tree: treasury -> irs -> irs-it-mod -> cade2,
       plus a sibling program 'ecm' (for cross-program tests)."""
    ts = broker_module.tenant_store
    rs = broker_module.role_store
    ts.put(Tenant(tenant_id="treasury", name="Treasury", level=TenantLevel.agency))
    ts.put(Tenant(tenant_id="irs", name="IRS", level=TenantLevel.bureau, parent_id="treasury"))
    ts.put(Tenant(tenant_id="irs-it-mod", name="IT Mod", level=TenantLevel.office, parent_id="irs"))
    ts.put(Tenant(tenant_id="cade2", name="CADE2", level=TenantLevel.program, parent_id="irs-it-mod"))
    ts.put(Tenant(tenant_id="ecm", name="ECM", level=TenantLevel.program, parent_id="irs-it-mod"))
    rs.put(RoleBinding(principal="alice@gov", tenant_id="cade2", role=Role.program_team))
    rs.put(RoleBinding(principal="bob@gov", tenant_id="irs", role=Role.bureau_admin))
    rs.put(RoleBinding(principal="dave@gov", tenant_id="irs", role=Role.auditor))


# ── Basic auth path stays open (back-compat) ──────────────────────────


@mock_aws
def test_basic_auth_bypasses_rbac(broker_phase3: Any) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        r = client.put(
            "/v2/service_instances/i-basic",
            json=_provision_body(),
            auth=("broker", "broker"),
        )
        assert r.status_code == 201, r.text


@mock_aws
def test_anonymous_cannot_provision(broker_phase3: Any) -> None:
    with TestClient(broker_phase3.app) as client:
        r = client.put(
            "/v2/service_instances/i-anon",
            json=_provision_body(),
        )
        assert r.status_code == 401


# ── JWT RBAC ──────────────────────────────────────────────────────────


@mock_aws
def test_program_team_member_can_provision_in_own_program(
    broker_phase3: Any,
) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        token = mint_dev_token(sub="alice@gov", tenant_id="cade2")
        r = client.put(
            "/v2/service_instances/i-cade2",
            json=_provision_body(organization_guid="cade2"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201, r.text


@mock_aws
def test_program_team_member_cannot_provision_in_sibling_program(
    broker_phase3: Any,
) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        # Alice (program-team cade2) tries to act on ecm.
        token = mint_dev_token(sub="alice@gov", tenant_id="cade2")
        r = client.put(
            "/v2/service_instances/i-ecm-x",
            json=_provision_body(organization_guid="ecm"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert detail["action"] == "provision"
        assert detail["tenant_id"] == "ecm"

    # An rbac.denied audit was emitted.
    rbac = [e for e in broker_phase3._test_emitted if e["action"] == "rbac.denied"]
    assert len(rbac) == 1
    assert rbac[0]["actor"] == "alice@gov"


@mock_aws
def test_bureau_admin_can_provision_in_descendant_program(
    broker_phase3: Any,
) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        # Bob is bureau-admin on irs -> inherits down to cade2.
        token = mint_dev_token(sub="bob@gov")
        r = client.put(
            "/v2/service_instances/i-bob",
            json=_provision_body(organization_guid="cade2"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201, r.text


@mock_aws
def test_auditor_cannot_provision(broker_phase3: Any) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        token = mint_dev_token(sub="dave@gov")
        r = client.put(
            "/v2/service_instances/i-dave",
            json=_provision_body(organization_guid="cade2"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


# ── Quota gate (3.4 + 3.6) ────────────────────────────────────────────


@mock_aws
def test_quota_cap_rejects_with_breakdown(broker_phase3: Any) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        # Cap of 1, then provision once -> ok. Provision twice -> reject.
        broker_phase3.quota_store.put(
            Quota(
                tenant_id="cade2",
                scope=service_type_scope("sovereign-envoy-lb"),
                max_instances=1,
            )
        )
        # But our metering is stubbed so usage stays at 0 — fake the count
        # by writing one synthetic usage record directly to the real UsageStore.
        from sovereign.models import Usage
        from sovereign.usage_store import UsageStore

        UsageStore().record(
            Usage(
                tenant_id="cade2",
                resource_id="prior-lb",
                resource_type="instance",
                quantity=1,
                unit="instance",
                metadata={"service_type": "sovereign-envoy-lb"},
            )
        )

        token = mint_dev_token(sub="alice@gov")
        r = client.put(
            "/v2/service_instances/i-over-cap",
            json=_provision_body(organization_guid="cade2"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text
        detail = r.json()["detail"]
        assert detail["message"] == "quota exceeded"
        assert any("per-service cap" in r for r in detail["reasons"])
        # Breakdown includes the exhausted entry.
        assert detail["breakdown"][0]["scope"] == service_type_scope("sovereign-envoy-lb")
        assert detail["breakdown"][0]["used_instances"] == 1
        assert detail["breakdown"][0]["max_instances"] == 1

    # quota.exceeded audit emitted
    qa = [e for e in broker_phase3._test_emitted if e["action"] == "quota.exceeded"]
    assert len(qa) == 1


# ── Tenant context lifted into policy input ───────────────────────────


@mock_aws
def test_tenant_metadata_lifts_into_policy_input(broker_phase3: Any) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        # Annotate cade2 with per-tenant CM-7 + gov-region overrides.
        broker_phase3.tenant_store.put(
            Tenant(
                tenant_id="cade2",
                name="CADE2",
                level=TenantLevel.program,
                parent_id="irs-it-mod",
                metadata={
                    "approved_services": ["sovereign-envoy-lb"],
                    "approved_regions": ["us-gov-west-1"],
                    "approved_plans": {
                        "sovereign-envoy-lb": ["standard-regional", "multi-region"],
                    },
                },
            )
        )
        token = mint_dev_token(sub="alice@gov", extra={"amr": ["pwd", "mfa"]})
        r = client.put(
            "/v2/service_instances/i-context",
            json=_provision_body(organization_guid="cade2"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201, r.text

    policy_input = broker_phase3._test_policy_inputs[-1]
    assert policy_input["approved_services"] == ["sovereign-envoy-lb"]
    assert policy_input["approved_regions"] == ["us-gov-west-1"]
    assert policy_input["approved_plans"] == {
        "sovereign-envoy-lb": ["standard-regional", "multi-region"]
    }
    # JWT user's groups are surfaced under context.caller_groups when set.
    assert policy_input["tenant_id"] == "cade2"
    assert policy_input["context"]["auth_scheme"] == "oidc"
    assert policy_input["context"]["require_mfa"] is True
    assert policy_input["context"]["amr"] == ["pwd", "mfa"]


# ── /v2/usage ─────────────────────────────────────────────────────────


@mock_aws
def test_usage_endpoint_returns_summary(broker_phase3: Any) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        broker_phase3.quota_store.put(
            Quota(
                tenant_id="cade2",
                scope=service_type_scope("sovereign-envoy-lb"),
                max_instances=5,
            )
        )
        # Auditor at irs can read cade2 (inherits down).
        token = mint_dev_token(sub="dave@gov")
        r = client.get(
            "/v2/usage/cade2", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["tenant_id"] == "cade2"
        entries = body["entries"]
        scopes = {e["scope"] for e in entries}
        assert service_type_scope("sovereign-envoy-lb") in scopes


@mock_aws
def test_usage_endpoint_requires_read(broker_phase3: Any) -> None:
    with TestClient(broker_phase3.app) as client:
        _seed_tree(broker_phase3)
        # alice has program-team on cade2 only — no read on ecm.
        token = mint_dev_token(sub="alice@gov")
        r = client.get(
            "/v2/usage/ecm", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 403
