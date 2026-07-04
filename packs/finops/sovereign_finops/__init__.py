"""Sovereign FinOps Pack — the chassis's first service pack (proof pack).

FinOps is the ideal first pack precisely because it needs *no new
deployment backend*: it reads the chassis's existing metering/`Usage`
records and adds a costing, budgeting, and chargeback layer plus a policy
bundle that can deny provisioning when a tenant is over budget. That
validates the whole pack pipeline — entry-point discovery, catalog
contribution, layered OPA policy — with zero infrastructure risk, before
the heavier packs (AI, Data) that exercise the Kubernetes/Terraform
executors.

It contributes:
  - two UI-surfaced, renderer-less service types (budget, chargeback-report)
    via `extra_service_catalog`,
  - a `sovereign.pack.finops` OPA bundle with a budget-breach deny rule,
  - cost/budget/chargeback models (see models.py).

Discovery: installing this wheel into a chassis venv registers it through
the `sovereign.packs` entry point declared in pyproject.toml — no chassis
code changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from sovereign.packs import BasePack

from .models import (
    Budget,
    ChargebackReport,
    CostModel,
    CostRate,
    budget_status,
    chargeback,
)

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry

_POLICY_DIR = Path(__file__).parent / "policies"


def _catalog_entries() -> list[ServiceCatalogEntry]:
    # Imported here (not at module top) so the pack module imports cleanly
    # even in environments that only need the models, and to avoid a hard
    # import cycle during chassis startup.
    from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

    budget = ServiceCatalogEntry(
        service_type="budget",
        name="Spend budget",
        description="Set a monthly spend ceiling for a tenant or service scope; "
        "provisioning is denied once the budget is breached.",
        bindable=False,
        tags=["finops", "governance", "cost"],
        pack="finops",
        plans=[
            ServicePlan(id="soft", name="soft", description="Warn on breach (audit only)."),
            ServicePlan(id="hard", name="hard", description="Deny provisioning on breach."),
        ],
        parameter_schema=ParameterSchema(
            schema={
                "type": "object",
                "required": ["scope", "limit"],
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "tenant | service_type:<name> | pack:<name>",
                        "default": "tenant",
                    },
                    "limit": {"type": "number", "minimum": 0},
                    "currency": {"type": "string", "default": "USD"},
                    "period": {"type": "string", "enum": ["monthly", "lifetime"], "default": "monthly"},
                },
            }
        ),
        metadata={"controls": ["SA-2", "PM-3"], "ui_section": "FinOps"},
    )
    report = ServiceCatalogEntry(
        service_type="chargeback-report",
        name="Chargeback report",
        description="Generate a costed breakdown of a tenant's metered usage "
        "for chargeback / showback.",
        bindable=False,
        tags=["finops", "reporting", "cost"],
        pack="finops",
        plans=[ServicePlan(id="on-demand", name="on-demand", description="Run a report now.")],
        parameter_schema=ParameterSchema(
            schema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "period": {"type": "string", "default": "monthly"},
                },
            }
        ),
        metadata={"controls": ["AU-6", "PM-3"], "ui_section": "FinOps"},
    )
    return [budget, report]


class Pack(BasePack):
    name = "sovereign-finops-pack"
    version = "0.1.0"
    description = "Cost models, budgets, and chargeback over the chassis metering layer."
    maturity = "ga"
    maturity_summary = "Low-risk governance pack backed by chassis metering; ready for controlled production use."

    renderers: ClassVar[list] = []  # renderer-less: reads existing metering data
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]
    extra_service_catalog: ClassVar[list] = []  # populated in __init_subclass__-free hook below


# Populate the catalog lazily at import time without forcing a chassis
# catalog import at module load (keeps `import sovereign_finops.models`
# cheap for unit tests).
def _install_catalog() -> None:
    if not Pack.extra_service_catalog:
        Pack.extra_service_catalog = _catalog_entries()


__all__ = [
    "Budget",
    "ChargebackReport",
    "CostModel",
    "CostRate",
    "Pack",
    "budget_status",
    "chargeback",
]
