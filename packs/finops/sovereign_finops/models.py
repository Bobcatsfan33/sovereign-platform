"""FinOps domain models — cost rates, budgets, and chargeback reports.

The pack adds a costing layer *on top of* the chassis metering data. It
introduces no new infrastructure: a `CostModel` maps (service_type, unit)
to a price, and `chargeback()` turns a tenant's `Usage` records into a
`ChargebackReport`. This is what makes FinOps the ideal proof pack — it
exercises pack discovery, catalog, and policy end-to-end against data the
chassis already produces.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sovereign.models import Usage


class CostRate(BaseModel):
    """Price for one unit of a metered resource.

    `service_type` of "*" is a catch-all default. `unit` matches the
    `Usage.unit` field emitted by the chassis metering client
    (e.g. "instance", "hour")."""

    service_type: str
    unit: str
    price_per_unit: float = Field(ge=0)
    currency: str = "USD"


class CostModel(BaseModel):
    """An ordered set of CostRates. Lookup prefers an exact
    (service_type, unit) match, then a ("*", unit) default, else 0."""

    rates: list[CostRate] = Field(default_factory=list)

    def price(self, service_type: str, unit: str) -> float:
        exact = next(
            (r for r in self.rates if r.service_type == service_type and r.unit == unit),
            None,
        )
        if exact is not None:
            return exact.price_per_unit
        default = next((r for r in self.rates if r.service_type == "*" and r.unit == unit), None)
        return default.price_per_unit if default is not None else 0.0


class Budget(BaseModel):
    """A spend ceiling for a (tenant_id, scope) over a period. `scope`
    mirrors the chassis quota scopes ("service_type:<t>" / "pack:<p>" /
    "tenant" for the whole tenant)."""

    tenant_id: str
    scope: str = "tenant"
    limit: float = Field(ge=0)
    currency: str = "USD"
    period: str = "monthly"


class ChargebackLineItem(BaseModel):
    service_type: str
    unit: str
    quantity: float
    unit_price: float
    cost: float


class ChargebackReport(BaseModel):
    tenant_id: str
    currency: str = "USD"
    total_cost: float = 0.0
    line_items: list[ChargebackLineItem] = Field(default_factory=list)


def chargeback(
    tenant_id: str,
    usage: list[Usage],
    model: CostModel,
    *,
    currency: str = "USD",
) -> ChargebackReport:
    """Aggregate a tenant's Usage records into a costed chargeback report.

    Groups by (service_type, unit), sums quantity, applies the cost
    model. service_type is read from `Usage.metadata['service_type']`
    (what the broker's metering client records), falling back to the
    resource_type when absent."""
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for u in usage:
        svc = str((u.metadata or {}).get("service_type") or u.resource_type)
        grouped[(svc, u.unit)] += u.quantity

    items: list[ChargebackLineItem] = []
    total = 0.0
    for (svc, unit), qty in sorted(grouped.items()):
        price = model.price(svc, unit)
        cost = round(price * qty, 6)
        total += cost
        items.append(
            ChargebackLineItem(
                service_type=svc, unit=unit, quantity=qty, unit_price=price, cost=cost
            )
        )
    return ChargebackReport(
        tenant_id=tenant_id,
        currency=currency,
        total_cost=round(total, 6),
        line_items=items,
    )


def budget_status(report: ChargebackReport, budgets: list[Budget]) -> list[dict]:
    """Compare a chargeback report against tenant budgets. Returns one
    dict per matching budget with used / limit / breached. Only
    tenant-wide ("tenant") and matching service_type scopes are checked
    here; pack scope is computed by the caller who knows the pack."""
    out: list[dict] = []
    for b in budgets:
        if b.tenant_id != report.tenant_id:
            continue
        if b.scope == "tenant":
            used = report.total_cost
        elif b.scope.startswith("service_type:"):
            svc = b.scope.removeprefix("service_type:")
            used = sum(li.cost for li in report.line_items if li.service_type == svc)
        else:
            continue
        out.append(
            {
                "scope": b.scope,
                "used": round(used, 6),
                "limit": b.limit,
                "currency": b.currency,
                "breached": used > b.limit,
            }
        )
    return out
