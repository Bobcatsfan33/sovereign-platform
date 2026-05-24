"""Tests for the OPA policy client and broker policy gate (Phase 2 tasks 2.2 + 2.7)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.models import PolicyDecision
from sovereign.policy import PolicyClient, build_policy_input, policy_request_from_input

# ── build_policy_input ────────────────────────────────────────────────


def test_build_policy_input_minimal() -> None:
    doc = build_policy_input(
        actor="alice",
        tenant_id="agency-x",
        service_type="sovereign-envoy-lb",
        plan_id="standard-regional",
        parameters={"region": "us-gov-west-1"},
    )
    assert doc["actor"] == "alice"
    assert doc["tenant_id"] == "agency-x"
    assert doc["service_type"] == "sovereign-envoy-lb"
    assert doc["parameters"] == {"region": "us-gov-west-1"}
    assert doc["context"] == {}
    # Opt-in fields not included when None.
    assert "approved_services" not in doc
    assert "approved_regions" not in doc


def test_build_policy_input_with_tenant_limits() -> None:
    doc = build_policy_input(
        actor="alice",
        tenant_id="agency-x",
        service_type="sovereign-envoy-lb",
        plan_id="standard-regional",
        parameters={},
        approved_services=["sovereign-envoy-lb"],
        approved_plans={"sovereign-envoy-lb": ["standard-regional"]},
        approved_regions=["us-gov-west-1"],
        context={"environment": "production"},
    )
    assert doc["approved_services"] == ["sovereign-envoy-lb"]
    assert doc["approved_plans"] == {"sovereign-envoy-lb": ["standard-regional"]}
    assert doc["approved_regions"] == ["us-gov-west-1"]
    assert doc["context"]["environment"] == "production"


def test_policy_request_from_input_round_trip() -> None:
    doc = build_policy_input(
        actor="alice", tenant_id="t", service_type="svc", plan_id="p", parameters={"x": 1}
    )
    req = policy_request_from_input(doc)
    assert req.tenant_id == "t"
    assert req.actor == "alice"
    assert req.action == "provision"
    assert req.resource == "svc"


# ── PolicyClient HTTP behaviour ───────────────────────────────────────


def _client_with_mock(handler) -> PolicyClient:
    c = PolicyClient()
    c._client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[assignment]
    return c


def test_evaluate_allow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/data/sovereign/decision")
        body = json.loads(request.content)
        assert body["input"]["service_type"] == "sovereign-envoy-lb"
        return httpx.Response(
            200, json={"result": {"allow": True, "denies": [], "matched_layers": []}}
        )

    c = _client_with_mock(handler)
    decision = c.evaluate(
        build_policy_input(
            actor="a", tenant_id="t", service_type="sovereign-envoy-lb",
            plan_id="p", parameters={},
        )
    )
    assert decision.allow is True
    assert decision.denies == []
    assert decision.matched_layers == []


def test_evaluate_deny_surfaces_denies() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "allow": False,
                    "denies": ["SC-8: TLS required", "gov-region: us-east-1 not allowed"],
                    "matched_layers": ["base"],
                }
            },
        )

    c = _client_with_mock(handler)
    decision = c.evaluate({})
    assert decision.allow is False
    assert len(decision.denies) == 2
    assert decision.matched_layers == ["base"]
    # The human reason is the joined denies
    assert "SC-8" in decision.reason


def test_evaluate_transport_error_fails_closed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("OPA down")

    c = _client_with_mock(handler)
    decision = c.evaluate({})
    assert decision.allow is False
    assert "transport error" in decision.reason
    assert decision.matched_layers == ["transport"]


def test_evaluate_500_response_fails_closed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    c = _client_with_mock(handler)
    decision = c.evaluate({})
    assert decision.allow is False
    assert "OPA returned 500" in decision.reason


def test_evaluate_missing_result_treats_as_deny() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # OPA returns {"result": null} when the decision path is undefined.
        return httpx.Response(200, json={})

    c = _client_with_mock(handler)
    decision = c.evaluate({})
    assert decision.allow is False
    assert "undefined" in decision.reason


def test_evaluate_malformed_json_fails_closed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    c = _client_with_mock(handler)
    decision = c.evaluate({})
    assert decision.allow is False
    assert "malformed" in decision.reason


def test_evaluate_fail_open_allows_on_transport_error() -> None:
    c = PolicyClient(fail_closed=False)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("OPA down")

    c._client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[assignment]
    decision = c.evaluate({})
    assert decision.allow is True
    assert "policy bypass" in decision.reason


def test_close_releases_client() -> None:
    PolicyClient().close()


# ── Broker policy gate ────────────────────────────────────────────────


@pytest.fixture
def broker_with_policy(broker_module: Any, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Broker wired with stubbed render + audit but with a *configurable*
    fake policy client so each test can install allow / deny behaviour."""
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

    # Each test installs its own policy stub via broker_with_policy.set_policy.
    class _Holder:
        decision: PolicyDecision = PolicyDecision(allow=True, denies=[], matched_layers=[])

    h = _Holder()

    class FakePolicy:
        def evaluate(self, _input: Any) -> PolicyDecision:
            return h.decision

    monkeypatch.setattr(broker_module, "policy", FakePolicy())
    broker_module._test_emitted = emitted  # type: ignore[attr-defined]
    broker_module._test_set_policy = lambda d: setattr(h, "decision", d)  # type: ignore[attr-defined]
    return broker_module


def _provision_body() -> dict[str, Any]:
    return {
        "service_id": "sovereign-envoy-lb",
        "plan_id": "standard-regional",
        "organization_guid": "agency-x",
        "parameters": {
            "region": "us-gov-west-1",
            "listeners": [{"name": "http", "port": 8080, "protocol": "HTTP"}],
            "routes": [{"host": "app.local", "prefix": "/", "cluster": "app"}],
            "clusters": [{"name": "app", "endpoints": ["127.0.0.1:3000"]}],
        },
    }


@mock_aws
def test_provision_allowed_emits_allow_audit(broker_with_policy: Any) -> None:
    broker_with_policy._test_set_policy(
        PolicyDecision(allow=True, denies=[], matched_layers=[])
    )
    with TestClient(broker_with_policy.app) as client:
        r = client.put(
            "/v2/service_instances/i-ok",
            json=_provision_body(),
            auth=("broker", "broker"),
        )
        assert r.status_code == 201, r.text
    # The policy.evaluated audit event landed first, with decision='allow'.
    policy_audits = [
        e for e in broker_with_policy._test_emitted if e["action"] == "policy.evaluated"
    ]
    assert len(policy_audits) == 1
    assert policy_audits[0]["decision"] == "allow"
    assert policy_audits[0]["tenant_id"] == "agency-x"
    assert policy_audits[0]["metadata"]["action"] == "provision"


@mock_aws
def test_provision_denied_returns_403_with_denies(broker_with_policy: Any) -> None:
    broker_with_policy._test_set_policy(
        PolicyDecision(
            allow=False,
            denies=[
                "SC-8: TLS must be enabled on network-facing service 'sovereign-envoy-lb'",
                "gov-region: 'us-east-1' is not an approved GovCloud region",
            ],
            matched_layers=["base"],
        )
    )
    with TestClient(broker_with_policy.app) as client:
        r = client.put(
            "/v2/service_instances/i-deny",
            json=_provision_body(),
            auth=("broker", "broker"),
        )
    assert r.status_code == 403
    body = r.json()
    # Broker uses RFC 7807 problem-detail; the structured detail is
    # nested under the standard 'detail' key.
    detail = body["detail"]
    assert detail["message"] == "policy rejected the request"
    assert len(detail["denies"]) == 2
    assert "SC-8" in detail["denies"][0]
    assert detail["matched_layers"] == ["base"]

    # Audit recorded the deny with the same denies + matched_layers.
    audit_evt = next(
        e for e in broker_with_policy._test_emitted if e["action"] == "policy.evaluated"
    )
    assert audit_evt["decision"] == "deny"
    assert audit_evt["metadata"]["denies"] == detail["denies"]
    assert audit_evt["metadata"]["matched_layers"] == ["base"]


@mock_aws
def test_provision_denied_does_not_persist_state(broker_with_policy: Any) -> None:
    """A policy-rejected request must NOT create an instance or call render()."""
    broker_with_policy._test_set_policy(
        PolicyDecision(allow=False, denies=["AC-6: blocked"], matched_layers=["base"])
    )

    with TestClient(broker_with_policy.app) as client:
        r = client.put(
            "/v2/service_instances/i-rejected",
            json=_provision_body(),
            auth=("broker", "broker"),
        )
        assert r.status_code == 403
        # last_operation should report 'gone' — instance was never persisted.
        r2 = client.get(
            "/v2/service_instances/i-rejected/last_operation",
            auth=("broker", "broker"),
        )
        assert r2.json()["state"] == "gone"

    # render() was never called — the policy gate fires before the renderer.
    # (We can't assert on the broker's render exactly because broker_with_policy
    #  uses its own stub; the assertion is "no instance was provisioned".)
    actions = [e["action"] for e in broker_with_policy._test_emitted]
    assert "instance.provisioned" not in actions


@mock_aws
def test_update_re_evaluates_policy(broker_with_policy: Any) -> None:
    # Provision under allow…
    broker_with_policy._test_set_policy(PolicyDecision(allow=True, denies=[], matched_layers=[]))
    with TestClient(broker_with_policy.app) as client:
        r = client.put(
            "/v2/service_instances/i-mut",
            json=_provision_body(),
            auth=("broker", "broker"),
        )
        assert r.status_code == 201

        # …then update under deny. The PATCH must be rejected.
        broker_with_policy._test_set_policy(
            PolicyDecision(allow=False, denies=["SC-13: bad ciphers"], matched_layers=["base"])
        )
        r = client.patch(
            "/v2/service_instances/i-mut",
            json={"plan_id": "multi-region"},
            auth=("broker", "broker"),
        )
        assert r.status_code == 403

    # Two policy.evaluated emissions — one for provision (allow), one for update (deny).
    policy_audits = [
        e for e in broker_with_policy._test_emitted if e["action"] == "policy.evaluated"
    ]
    assert [e["decision"] for e in policy_audits] == ["allow", "deny"]
    assert policy_audits[1]["metadata"]["action"] == "update"


@mock_aws
def test_policy_engine_unavailable_fails_closed_at_broker(
    broker_with_policy: Any,
) -> None:
    broker_with_policy._test_set_policy(
        PolicyDecision(
            allow=False,
            denies=["policy engine unavailable: transport error: …"],
            matched_layers=["transport"],
            reason="policy engine unavailable",
        )
    )
    with TestClient(broker_with_policy.app) as client:
        r = client.put(
            "/v2/service_instances/i-opa-down",
            json=_provision_body(),
            auth=("broker", "broker"),
        )
        assert r.status_code == 403
        assert "transport" in str(r.json()["detail"]["matched_layers"])
