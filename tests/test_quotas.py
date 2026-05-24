"""Tests for the quota store + enforcer (Phase 3 tasks 3.4 + 3.6)."""

from __future__ import annotations

from moto import mock_aws
from sovereign.models import Usage
from sovereign.quotas import (
    Quota,
    QuotaEnforcer,
    QuotaStore,
    pack_scope,
    service_type_scope,
)
from sovereign.usage_store import UsageStore


def _seed_usage_records(usage: UsageStore, tenant_id: str, recs: list[dict]) -> None:
    for r in recs:
        usage.record(
            Usage(
                tenant_id=tenant_id,
                resource_id=r["resource_id"],
                resource_type=r.get("resource_type", "instance"),
                quantity=r.get("quantity", 1.0),
                unit=r.get("unit", "instance"),
                metadata=r.get("metadata", {}),
            )
        )


# ── QuotaStore round-trips ────────────────────────────────────────────


def test_quota_round_trip() -> None:
    with mock_aws():
        store = QuotaStore()
        store.ensure_table()
        q = Quota(
            tenant_id="cade2",
            scope=service_type_scope("sovereign-envoy-lb"),
            max_instances=5,
        )
        store.put(q)
        got = store.get("cade2", service_type_scope("sovereign-envoy-lb"))
        assert got is not None
        assert got.max_instances == 5


def test_quota_get_missing_returns_none() -> None:
    with mock_aws():
        store = QuotaStore()
        store.ensure_table()
        assert store.get("none", "x") is None


def test_quota_list_for_tenant() -> None:
    with mock_aws():
        store = QuotaStore()
        store.ensure_table()
        store.put(Quota(tenant_id="t", scope=service_type_scope("a"), max_instances=1))
        store.put(Quota(tenant_id="t", scope=service_type_scope("b"), max_instances=2))
        store.put(Quota(tenant_id="other", scope=service_type_scope("a"), max_instances=99))
        quotas = store.list_for_tenant("t")
        assert {q.scope for q in quotas} == {service_type_scope("a"), service_type_scope("b")}


def test_quota_delete() -> None:
    with mock_aws():
        store = QuotaStore()
        store.ensure_table()
        scope = service_type_scope("x")
        store.put(Quota(tenant_id="t", scope=scope, max_instances=1))
        store.delete("t", scope)
        assert store.get("t", scope) is None


def test_quota_ensure_table_idempotent() -> None:
    with mock_aws():
        store = QuotaStore()
        store.ensure_table()
        store.ensure_table()


# ── QuotaEnforcer.check_provision ─────────────────────────────────────


def test_check_provision_allows_when_no_quota_configured() -> None:
    with mock_aws():
        QuotaStore().ensure_table()
        UsageStore().ensure_table()
        enforcer = QuotaEnforcer()
        result = enforcer.check_provision(
            tenant_id="t", service_type="sovereign-envoy-lb"
        )
        assert result.allow is True
        assert result.reasons == []
        # Still produces a breakdown so callers see usage.
        assert any(e.scope == service_type_scope("sovereign-envoy-lb") for e in result.breakdown)


def test_check_provision_allows_when_under_cap() -> None:
    with mock_aws():
        quotas = QuotaStore()
        quotas.ensure_table()
        usage = UsageStore()
        usage.ensure_table()
        quotas.put(
            Quota(
                tenant_id="cade2",
                scope=service_type_scope("sovereign-envoy-lb"),
                max_instances=3,
            )
        )
        _seed_usage_records(
            usage,
            "cade2",
            [
                {"resource_id": "lb-1", "metadata": {"service_type": "sovereign-envoy-lb"}},
                {"resource_id": "lb-2", "metadata": {"service_type": "sovereign-envoy-lb"}},
            ],
        )
        enforcer = QuotaEnforcer(quotas=quotas, usage=usage)
        result = enforcer.check_provision(
            tenant_id="cade2", service_type="sovereign-envoy-lb"
        )
        assert result.allow is True
        # Breakdown shows 2 of 3 used
        per = next(e for e in result.breakdown if e.scope == service_type_scope("sovereign-envoy-lb"))
        assert per.used_instances == 2
        assert per.max_instances == 3


def test_check_provision_rejects_at_cap() -> None:
    with mock_aws():
        quotas = QuotaStore()
        quotas.ensure_table()
        usage = UsageStore()
        usage.ensure_table()
        quotas.put(
            Quota(
                tenant_id="cade2",
                scope=service_type_scope("sovereign-envoy-lb"),
                max_instances=2,
            )
        )
        _seed_usage_records(
            usage,
            "cade2",
            [
                {"resource_id": "lb-1", "metadata": {"service_type": "sovereign-envoy-lb"}},
                {"resource_id": "lb-2", "metadata": {"service_type": "sovereign-envoy-lb"}},
            ],
        )
        enforcer = QuotaEnforcer(quotas=quotas, usage=usage)
        result = enforcer.check_provision(
            tenant_id="cade2", service_type="sovereign-envoy-lb"
        )
        assert result.allow is False
        assert any("at the per-service cap" in r for r in result.reasons)
        per = next(e for e in result.breakdown if e.scope == service_type_scope("sovereign-envoy-lb"))
        assert per.at_limit is True


def test_check_provision_ignores_unrelated_service_types() -> None:
    with mock_aws():
        quotas = QuotaStore()
        quotas.ensure_table()
        usage = UsageStore()
        usage.ensure_table()
        # Cap of 1 on inference, but only LB usage exists -> allow.
        quotas.put(
            Quota(
                tenant_id="cade2",
                scope=service_type_scope("inference-endpoint"),
                max_instances=1,
            )
        )
        _seed_usage_records(
            usage,
            "cade2",
            [
                {"resource_id": "lb-1", "metadata": {"service_type": "sovereign-envoy-lb"}},
                {"resource_id": "lb-2", "metadata": {"service_type": "sovereign-envoy-lb"}},
            ],
        )
        enforcer = QuotaEnforcer(quotas=quotas, usage=usage)
        # Provisioning inference for the first time should pass
        assert enforcer.check_provision(
            tenant_id="cade2", service_type="inference-endpoint"
        ).allow is True


# ── Pack-aware quotas (3.6) ───────────────────────────────────────────


def test_check_provision_rejects_at_pack_cap_even_if_per_service_ok() -> None:
    """A pack-level cap of 3 across all AI-pack services rejects the
    next AI inference endpoint when the pack already has 3 instances
    in total — even though the per-service cap (if any) is fine."""
    with mock_aws():
        quotas = QuotaStore()
        quotas.ensure_table()
        usage = UsageStore()
        usage.ensure_table()
        quotas.put(
            Quota(tenant_id="cade2", scope=pack_scope("ai-pack"), max_instances=3)
        )
        _seed_usage_records(
            usage,
            "cade2",
            [
                {"resource_id": "ie-1", "metadata": {"service_type": "inference-endpoint", "pack": "ai-pack"}},
                {"resource_id": "rag-1", "metadata": {"service_type": "rag-workspace", "pack": "ai-pack"}},
                {"resource_id": "vdb-1", "metadata": {"service_type": "vector-db", "pack": "ai-pack"}},
            ],
        )
        enforcer = QuotaEnforcer(quotas=quotas, usage=usage)
        result = enforcer.check_provision(
            tenant_id="cade2", service_type="inference-endpoint", pack="ai-pack"
        )
        assert result.allow is False
        assert any("per-pack cap" in r for r in result.reasons)


def test_pack_quota_does_not_apply_to_other_packs() -> None:
    with mock_aws():
        quotas = QuotaStore()
        quotas.ensure_table()
        usage = UsageStore()
        usage.ensure_table()
        # Cap on ai-pack but provisioning a chassis (sovereign-envoy-lb) service
        quotas.put(
            Quota(tenant_id="cade2", scope=pack_scope("ai-pack"), max_instances=0)
        )
        enforcer = QuotaEnforcer(quotas=quotas, usage=usage)
        result = enforcer.check_provision(
            tenant_id="cade2", service_type="sovereign-envoy-lb", pack="chassis"
        )
        assert result.allow is True


# ── usage_summary feeds /v2/usage/{tenant_id} ─────────────────────────


def test_usage_summary_returns_configured_and_observed_scopes() -> None:
    with mock_aws():
        quotas = QuotaStore()
        quotas.ensure_table()
        usage = UsageStore()
        usage.ensure_table()
        # Configured quota for inference (no usage yet)
        quotas.put(
            Quota(
                tenant_id="cade2",
                scope=service_type_scope("inference-endpoint"),
                max_instances=5,
            )
        )
        # Observed LB usage (no quota configured)
        _seed_usage_records(
            usage,
            "cade2",
            [
                {"resource_id": "lb-1", "metadata": {"service_type": "sovereign-envoy-lb"}},
            ],
        )
        enforcer = QuotaEnforcer(quotas=quotas, usage=usage)
        summary = enforcer.usage_summary("cade2")
        scopes = {e.scope for e in summary}
        assert service_type_scope("inference-endpoint") in scopes
        assert service_type_scope("sovereign-envoy-lb") in scopes
        # The LB entry has used=1, max=None (unbounded but observable)
        lb_entry = next(e for e in summary if e.scope == service_type_scope("sovereign-envoy-lb"))
        assert lb_entry.used_instances == 1
        assert lb_entry.max_instances is None


def test_usage_summary_handles_empty_tenant() -> None:
    with mock_aws():
        QuotaStore().ensure_table()
        UsageStore().ensure_table()
        enforcer = QuotaEnforcer()
        assert enforcer.usage_summary("never-seen") == []
