"""Tests for the FinOps pack (proof pack).

Exercises the cost model, chargeback aggregation, budget status, and that
the Pack registers cleanly through the chassis pack machinery and
contributes its catalog entries.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the pack importable without an install (mirrors how tests/conftest
# puts libs/common on the path).
PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_finops  # noqa: E402
from sovereign_finops import (  # noqa: E402
    Budget,
    CostModel,
    CostRate,
    budget_status,
    chargeback,
)
from sovereign_finops.models import ChargebackReport  # noqa: E402


def _usage(svc: str, qty: float, unit: str = "instance"):  # type: ignore[no-untyped-def]
    from sovereign.models import Usage

    return Usage(
        tenant_id="cade2",
        resource_id=f"r-{svc}-{qty}",
        resource_type="instance",
        quantity=qty,
        unit=unit,
        metadata={"service_type": svc},
    )


def _model() -> CostModel:
    return CostModel(
        rates=[
            CostRate(service_type="sovereign-envoy-lb", unit="instance", price_per_unit=10.0),
            CostRate(service_type="*", unit="instance", price_per_unit=1.0),
        ]
    )


def test_cost_model_exact_then_default_then_zero() -> None:
    m = _model()
    assert m.price("sovereign-envoy-lb", "instance") == 10.0  # exact
    assert m.price("inference-endpoint", "instance") == 1.0  # default
    assert m.price("anything", "hour") == 0.0  # no match


def test_chargeback_aggregates_and_costs() -> None:
    usage = [
        _usage("sovereign-envoy-lb", 2),
        _usage("sovereign-envoy-lb", 1),
        _usage("inference-endpoint", 5),
    ]
    report = chargeback("cade2", usage, _model())
    assert isinstance(report, ChargebackReport)
    # 3 LBs @10 + 5 inference @1 = 35
    assert report.total_cost == 35.0
    lb = next(li for li in report.line_items if li.service_type == "sovereign-envoy-lb")
    assert lb.quantity == 3
    assert lb.cost == 30.0


def test_chargeback_empty_usage() -> None:
    report = chargeback("cade2", [], _model())
    assert report.total_cost == 0.0
    assert report.line_items == []


def test_budget_status_tenant_scope_breach() -> None:
    report = chargeback("cade2", [_usage("sovereign-envoy-lb", 200)], _model())  # 2000
    statuses = budget_status(report, [Budget(tenant_id="cade2", scope="tenant", limit=1000)])
    assert len(statuses) == 1
    assert statuses[0]["breached"] is True
    assert statuses[0]["used"] == 2000.0


def test_budget_status_service_scope() -> None:
    report = chargeback(
        "cade2",
        [_usage("sovereign-envoy-lb", 5), _usage("inference-endpoint", 100)],
        _model(),
    )
    statuses = budget_status(
        report,
        [Budget(tenant_id="cade2", scope="service_type:sovereign-envoy-lb", limit=100)],
    )
    # LB cost = 50, under 100 -> not breached
    assert statuses[0]["used"] == 50.0
    assert statuses[0]["breached"] is False


def test_budget_status_ignores_other_tenants() -> None:
    report = chargeback("cade2", [_usage("sovereign-envoy-lb", 5)], _model())
    assert budget_status(report, [Budget(tenant_id="other", scope="tenant", limit=1)]) == []


def test_pack_registers_and_contributes_catalog() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry

    pack_registry.clear()
    sovereign_finops._install_catalog()
    pack = sovereign_finops.Pack()
    register_pack(pack)

    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-finops-pack" in names

    svc_types = {e.service_type for e in pack.extra_service_catalog}
    assert svc_types == {"budget", "chargeback-report"}
    # Catalog entries carry the finops pack tag + NIST controls.
    budget = next(e for e in pack.extra_service_catalog if e.service_type == "budget")
    assert budget.pack == "finops"
    assert "SA-2" in budget.metadata["controls"]


def test_pack_declares_policy_bundle() -> None:
    pack = sovereign_finops.Pack()
    assert len(pack.policy_bundles) == 1
    bundle = pack.policy_bundles[0]
    assert bundle.name == "policies"
    assert (bundle / "budget.rego").exists()
