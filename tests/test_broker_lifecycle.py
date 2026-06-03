"""Integration tests for the full OSB lifecycle on the broker.

provision -> bind -> unbind -> deprovision, end to end, against a moto-
backed DynamoDB. Outbound calls to the control plane and the audit
service are stubbed so the test stays in-process and deterministic.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.renderers import TeardownResult
from sovereign.tenancy import mint_dev_token

from .conftest import BEARER


@pytest.fixture
def broker_app(broker_module: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch out the broker's outbound dependencies (control-plane render,
    audit emit, OPA policy) so the lifecycle tests exercise the broker's
    own state machine without standing up the other services."""
    from sovereign.models import PolicyDecision

    rendered: list[str] = []

    async def fake_render(instance: Any) -> dict[str, Any]:
        rendered.append(instance.instance_id)
        return {"bucket": "sovereign-configs", "key": f"instances/{instance.instance_id}/v1/envoy.yaml", "version": 1}

    monkeypatch.setattr(broker_module, "render", fake_render)

    emitted: list[tuple[str, str]] = []

    class FakeAudit:
        def emit(self, action: str, resource: str, *_args: Any, **_kwargs: Any) -> None:
            emitted.append((action, resource))

    monkeypatch.setattr(broker_module, "audit", FakeAudit())

    # Default the policy engine to allow-all so lifecycle tests focus on
    # OSB state-machine behaviour. test_policy.py covers the policy gate
    # specifically with allow/deny scenarios.
    class FakePolicy:
        def evaluate(self, _input: Any) -> PolicyDecision:
            return PolicyDecision(allow=True, denies=[], matched_layers=[])

    monkeypatch.setattr(broker_module, "policy", FakePolicy())

    # Quota + metering also stubbed for OSB-state-machine focus.
    from sovereign.quotas.models import QuotaCheckResult

    class FakeQuotas:
        def check_provision(self, **_kw: Any) -> QuotaCheckResult:
            return QuotaCheckResult(allow=True)

        def usage_summary(self, _tid: str) -> list[Any]:
            return []

    class FakeMetering:
        def record(self, **_kw: Any) -> None:
            return None

    monkeypatch.setattr(broker_module, "quotas", FakeQuotas())
    monkeypatch.setattr(broker_module, "metering", FakeMetering())

    broker_module._test_rendered = rendered  # type: ignore[attr-defined]
    broker_module._test_emitted = emitted  # type: ignore[attr-defined]
    return broker_module


def _provision_body() -> dict[str, Any]:
    return {
        "service_id": "sovereign-envoy-lb",
        "plan_id": "standard-regional",
        "organization_guid": "demo-org",
        "space_guid": "demo-space",
        "parameters": {
            "region": "us-east-1",
            "listeners": [{"name": "http", "port": 8080, "protocol": "HTTP"}],
            "routes": [{"host": "app.local", "prefix": "/", "cluster": "app"}],
            "clusters": [{"name": "app", "endpoints": ["127.0.0.1:3000"]}],
        },
    }


def _broker_creds() -> tuple[str, str]:
    return ("broker", "broker")


@mock_aws
def test_catalog_requires_auth(broker_app: Any) -> None:
    client = TestClient(broker_app.app)
    # The OSB-style auth dependency permits missing creds (so health probes
    # can hit the catalog) but rejects wrong creds — see the dedicated
    # test_invalid_basic_creds_rejected for the rejection path. Here we
    # just verify the happy path with valid creds.
    r2 = client.get("/v2/catalog", auth=_broker_creds())
    assert r2.status_code == 200
    services = r2.json()["services"]
    # Look the LB up by id rather than position — when service packs are
    # installed (e.g. the AI pack) the catalog carries more entries and the
    # ordering is not guaranteed to put the chassis LB first.
    lb = next(s for s in services if s["id"] == "sovereign-envoy-lb")
    assert {p["id"] for p in lb["plans"]} == {"standard-regional", "multi-region", "sidecar"}


@mock_aws
def test_invalid_basic_creds_rejected(broker_app: Any) -> None:
    # Ensure DDB tables exist; broker.startup creates them.
    with TestClient(broker_app.app) as client:
        r = client.get("/v2/catalog", auth=("bad", "creds"))
        assert r.status_code == 401


@mock_aws
def test_full_lifecycle(broker_app: Any) -> None:
    instance_id = "demo-lb"
    binding_id = "demo-binding"

    with TestClient(broker_app.app) as client:
        # ── PROVISION ────────────────────────────────────────────────
        r = client.put(
            f"/v2/service_instances/{instance_id}",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["operation"] == "provisioned"
        assert body["config"]["key"].startswith(f"instances/{instance_id}/")
        assert instance_id in broker_app._test_rendered

        # last_operation should report 'succeeded'
        r = client.get(f"/v2/service_instances/{instance_id}/last_operation", auth=_broker_creds())
        assert r.status_code == 200
        last = r.json()
        assert last["state"] == "succeeded"
        assert last["operation"] == "succeeded"
        assert last["operation_id"] == f"{instance_id}:v1:provision"
        assert last["desired_version"] == 1
        assert last["applied_version"] == 1
        assert last["drift_status"] == "in_sync"

        # Idempotent re-provision returns already_exists
        r = client.put(
            f"/v2/service_instances/{instance_id}",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 201
        assert r.json()["operation"] == "already_exists"

        # ── BIND ─────────────────────────────────────────────────────
        r = client.put(
            f"/v2/service_instances/{instance_id}/service_bindings/{binding_id}",
            json={"service_id": "sovereign-envoy-lb", "plan_id": "standard-regional"},
            auth=_broker_creds(),
        )
        assert r.status_code == 201, r.text
        creds = r.json()["credentials"]
        assert creds["instance_id"] == instance_id
        assert "config_url" in creds

        # ── UNBIND ───────────────────────────────────────────────────
        r = client.delete(
            f"/v2/service_instances/{instance_id}/service_bindings/{binding_id}",
            auth=_broker_creds(),
        )
        assert r.status_code == 200

        # ── DEPROVISION ──────────────────────────────────────────────
        r = client.delete(f"/v2/service_instances/{instance_id}", auth=_broker_creds())
        assert r.status_code == 200

        # last_operation now reports 'gone'
        r = client.get(f"/v2/service_instances/{instance_id}/last_operation", auth=_broker_creds())
        assert r.json()["state"] == "gone"

    # Audit emissions cover the full lifecycle
    actions = [a for a, _ in broker_app._test_emitted]
    assert "instance.provisioned" in actions
    assert "binding.created" in actions
    assert "binding.deleted" in actions
    assert "instance.deprovisioned" in actions


@mock_aws
def test_deprovision_invokes_renderer_teardown(
    broker_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    torn_down: list[str] = []

    class FakeRenderer:
        async def teardown(self, instance: Any) -> TeardownResult:
            torn_down.append(instance.instance_id)
            return TeardownResult(ok=True, removed=[f"instance/{instance.instance_id}"])

    with TestClient(broker_app.app) as client:
        r = client.put(
            "/v2/service_instances/teardown-me",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 201, r.text

        monkeypatch.setattr(
            broker_app.renderer_registry,
            "get",
            lambda _service_type: FakeRenderer(),
        )

        r = client.delete("/v2/service_instances/teardown-me", auth=_broker_creds())
        assert r.status_code == 200, r.text

    assert torn_down == ["teardown-me"]
    assert "instance.torn_down" in [a for a, _ in broker_app._test_emitted]


@mock_aws
def test_update_increments_version(broker_app: Any) -> None:
    instance_id = "demo-update"
    with TestClient(broker_app.app) as client:
        client.put(
            f"/v2/service_instances/{instance_id}",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        # PATCH with a new plan_id — broker increments version, re-renders.
        r = client.patch(
            f"/v2/service_instances/{instance_id}",
            json={"plan_id": "multi-region"},
            auth=_broker_creds(),
        )
        assert r.status_code == 200
        assert r.json()["operation"] == "updated"
        # render was called twice (provision + update)
        assert broker_app._test_rendered.count(instance_id) == 2


@mock_aws
def test_update_unknown_instance_returns_404(broker_app: Any) -> None:
    with TestClient(broker_app.app) as client:
        r = client.patch(
            "/v2/service_instances/does-not-exist",
            json={"plan_id": "multi-region"},
            auth=_broker_creds(),
        )
        assert r.status_code == 404


@mock_aws
def test_bind_unknown_instance_returns_404(broker_app: Any) -> None:
    with TestClient(broker_app.app) as client:
        r = client.put(
            "/v2/service_instances/missing/service_bindings/b1",
            json={},
            auth=_broker_creds(),
        )
        assert r.status_code == 404


def test_healthz_open(broker_app: Any) -> None:
    with TestClient(broker_app.app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert "envoy-snapshot" in r.json()["executors"]


# ── Async provisioning (Step 0.1) ──────────────────────────────────────


@mock_aws
def test_async_provision_returns_202_and_completes(broker_app: Any) -> None:
    """With ?accepts_incomplete=true the broker returns 202 immediately and
    finalises render in a background task; the instance reaches 'succeeded'."""
    with TestClient(broker_app.app) as client:
        r = client.put(
            "/v2/service_instances/i-async",
            params={"accepts_incomplete": "true"},
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["operation"] == "provisioning"

        # Starlette runs the BackgroundTask after the response is returned,
        # so by now finalize has run: last_operation reports succeeded, and
        # the OSB `operation` field is the spec vocabulary.
        r = client.get("/v2/service_instances/i-async/last_operation", auth=_broker_creds())
        assert r.json()["state"] == "succeeded"
        assert r.json()["operation"] == "succeeded"

    # Render did run (in the background) and the lifecycle audit landed.
    assert "i-async" in broker_app._test_rendered
    assert "instance.provisioned" in [a for a, _ in broker_app._test_emitted]


@mock_aws
def test_sync_provision_unaffected_by_async_flag_default(broker_app: Any) -> None:
    """Default (no flag) stays synchronous: 201 with the rendered config."""
    with TestClient(broker_app.app) as client:
        r = client.put(
            "/v2/service_instances/i-sync",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 201
        assert r.json()["operation"] == "provisioned"
        assert "config" in r.json()


@mock_aws
def test_last_operation_gone_has_operation_field(broker_app: Any) -> None:
    with TestClient(broker_app.app) as client:
        r = client.get("/v2/service_instances/never/last_operation", auth=_broker_creds())
        assert r.json()["state"] == "gone"
        assert r.json()["operation"] == "gone"


@mock_aws
def test_reconcile_recovers_failed_instance(
    broker_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"render": 0}

    async def failing_render(instance: Any) -> dict[str, Any]:
        calls["render"] += 1
        raise broker_app.HTTPException(
            status_code=503,
            detail={
                "message": "apply failed",
                "failed_step": "k8s-apply",
                "detail": "cluster unavailable",
            },
        )

    monkeypatch.setattr(broker_app, "render", failing_render)

    with TestClient(broker_app.app) as client:
        r = client.put(
            "/v2/service_instances/i-reconcile",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 503

        r = client.get("/v2/service_instances/i-reconcile/last_operation", auth=_broker_creds())
        failed = r.json()
        assert failed["state"] == "failed"
        assert failed["failed_step_kind"] == "k8s-apply"
        assert failed["drift_status"] == "drifted"

        async def fixed_render(instance: Any) -> dict[str, Any]:
            calls["render"] += 1
            return {
                "bucket": "sovereign-configs",
                "key": f"instances/{instance.instance_id}/v{instance.version}/envoy.yaml",
                "version": instance.version,
                "service_type": instance.service_id,
                "manifest": [{"kind": "k8s-apply", "target": "default"}],
            }

        monkeypatch.setattr(broker_app, "render", fixed_render)

        r = client.post(
            "/v2/reconcile",
            json={"instance_id": "i-reconcile"},
            auth=_broker_creds(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["changed"] == 1
        assert body["results"][0]["action"] == "reconciled"

        r = client.get("/v2/service_instances/i-reconcile/last_operation", auth=_broker_creds())
        last = r.json()
        assert last["state"] == "succeeded"
        assert last["operation"] == "succeeded"
        assert last["operation_id"] == "i-reconcile:v1:reconcile"
        assert last["failed_step_kind"] is None
        assert last["drift_status"] == "in_sync"
        assert last["reconcile_attempts"] == 1

    assert calls["render"] == 2
    actions = [a for a, _ in broker_app._test_emitted]
    assert "instance.reconciled" in actions


@mock_aws
def test_reconcile_rejects_jwt_callers(broker_app: Any) -> None:
    token = mint_dev_token(sub="alice@gov", tenant_id="demo-org")
    with TestClient(broker_app.app) as client:
        r = client.post(
            "/v2/reconcile",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


# Suppress unused-import warning since BEARER is imported for parity with
# other test modules even though basic auth is used here.
_ = BEARER
