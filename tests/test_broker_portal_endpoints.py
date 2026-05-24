"""Phase 4 backend support: tests for the broker /v2/instances and
/v2/policy/check endpoints, plus CORS headers on broker + audit."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.models import PolicyDecision


@pytest.fixture
def broker_app(broker_module: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Broker with stubbed downstream services for endpoint tests."""

    async def fake_render(instance: Any) -> dict[str, Any]:
        return {"bucket": "b", "key": f"instances/{instance.instance_id}/v1/envoy.yaml", "version": 1}

    class FakeAudit:
        def emit(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    captured_inputs: list[dict[str, Any]] = []

    class FakePolicy:
        def __init__(self) -> None:
            self.decision = PolicyDecision(allow=True, denies=[], matched_layers=[])

        def evaluate(self, policy_input: dict[str, Any]) -> PolicyDecision:
            captured_inputs.append(policy_input)
            return self.decision

    fake_policy = FakePolicy()
    monkeypatch.setattr(broker_module, "render", fake_render)
    monkeypatch.setattr(broker_module, "audit", FakeAudit())
    monkeypatch.setattr(broker_module, "policy", fake_policy)
    broker_module._test_policy_inputs = captured_inputs  # type: ignore[attr-defined]
    broker_module._test_policy = fake_policy  # type: ignore[attr-defined]
    return broker_module


def _basic() -> tuple[str, str]:
    return ("broker", "broker")


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


# ── /v2/instances ────────────────────────────────────────────────────


@mock_aws
def test_list_instances_basic_caller_returns_everything(broker_app: Any) -> None:
    with TestClient(broker_app.app) as client:
        client.put("/v2/service_instances/i-a", json=_provision_body(), auth=_basic())
        body = {**_provision_body(), "organization_guid": "agency-y"}
        client.put("/v2/service_instances/i-b", json=body, auth=_basic())

        r = client.get("/v2/instances", auth=_basic())
        assert r.status_code == 200
        payload = r.json()
        ids = sorted(i["instance_id"] for i in payload["instances"])
        assert ids == ["i-a", "i-b"]
        assert payload["count"] == 2


@mock_aws
def test_list_instances_filters_by_tenant(broker_app: Any) -> None:
    with TestClient(broker_app.app) as client:
        client.put("/v2/service_instances/i-a", json=_provision_body(), auth=_basic())
        body = {**_provision_body(), "organization_guid": "agency-y"}
        client.put("/v2/service_instances/i-b", json=body, auth=_basic())

        r = client.get("/v2/instances", params={"tenant_id": "agency-y"}, auth=_basic())
        assert r.status_code == 200
        payload = r.json()
        assert [i["instance_id"] for i in payload["instances"]] == ["i-b"]


# ── /v2/policy/check ─────────────────────────────────────────────────


def test_policy_check_returns_allow(broker_app: Any) -> None:
    broker_app._test_policy.decision = PolicyDecision(allow=True, denies=[], matched_layers=[])
    with TestClient(broker_app.app) as client:
        r = client.post(
            "/v2/policy/check",
            json={
                "service_id": "sovereign-envoy-lb",
                "plan_id": "standard-regional",
                "tenant_id": "agency-x",
                "parameters": {"region": "us-gov-west-1", "tls": True},
            },
            auth=_basic(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["allow"] is True
        assert body["denies"] == []

    # The endpoint passes the input through to the policy engine unchanged.
    captured = broker_app._test_policy_inputs[-1]
    assert captured["service_type"] == "sovereign-envoy-lb"
    assert captured["tenant_id"] == "agency-x"
    assert captured["parameters"]["region"] == "us-gov-west-1"


def test_policy_check_returns_deny_with_reasons(broker_app: Any) -> None:
    broker_app._test_policy.decision = PolicyDecision(
        allow=False,
        denies=["SC-8: TLS required", "gov-region: us-east-1 not allowed"],
        matched_layers=["base"],
        reason="SC-8: TLS required; gov-region: us-east-1 not allowed",
    )
    with TestClient(broker_app.app) as client:
        r = client.post(
            "/v2/policy/check",
            json={
                "service_id": "sovereign-envoy-lb",
                "plan_id": "standard-regional",
                "tenant_id": "agency-x",
                "parameters": {"region": "us-east-1", "tls": False},
            },
            auth=_basic(),
        )
        # /v2/policy/check itself always 200s — it's a what-if, not the
        # gated provision call. The body tells the caller what would happen.
        assert r.status_code == 200
        body = r.json()
        assert body["allow"] is False
        assert "SC-8" in body["denies"][0]
        assert body["matched_layers"] == ["base"]


def test_policy_check_does_not_emit_audit_event(broker_app: Any) -> None:
    """The wizard calls this many times as parameters change; auditing
    each one would flood the trail. The real audit lands at provision."""
    emitted: list[Any] = []

    class CountingAudit:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            emitted.append((args, kwargs))

    broker_app.audit = CountingAudit()
    with TestClient(broker_app.app) as client:
        r = client.post(
            "/v2/policy/check",
            json={
                "service_id": "sovereign-envoy-lb",
                "plan_id": "standard-regional",
                "tenant_id": "agency-x",
                "parameters": {},
            },
            auth=_basic(),
        )
        assert r.status_code == 200
    assert emitted == []


# ── CORS ─────────────────────────────────────────────────────────────


def test_broker_cors_preflight_allows_portal_origin(broker_app: Any) -> None:
    client = TestClient(broker_app.app)
    r = client.options(
        "/v2/catalog",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    # Starlette's CORSMiddleware returns 200 on a valid preflight.
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "GET" in r.headers.get("access-control-allow-methods", "")


def test_broker_cors_rejects_unknown_origin(broker_app: Any) -> None:
    client = TestClient(broker_app.app)
    r = client.options(
        "/v2/catalog",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    # Starlette returns 400 for a preflight with an origin not on the allow-list.
    assert r.status_code in (400, 403)
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_audit_service_cors(audit_service_module: Any) -> None:
    client = TestClient(audit_service_module.app)
    r = client.options(
        "/events",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
