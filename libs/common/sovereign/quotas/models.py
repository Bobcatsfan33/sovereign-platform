"""Pydantic models for quotas + the enforcer's return shape."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def service_type_scope(service_type: str) -> str:
    """Canonical quota scope for a single service type."""
    return f"service_type:{service_type}"


def pack_scope(pack: str) -> str:
    """Canonical quota scope for a whole pack (rolls up its service types)."""
    return f"pack:{pack}"


class Quota(BaseModel):
    """A quota record: how much of `scope` the tenant may consume."""

    tenant_id: str
    scope: str
    max_instances: int | None = None
    max_compute_units: float | None = None
    period: Literal["monthly", "lifetime"] = "lifetime"
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QuotaCheckResult(BaseModel):
    """Returned by `QuotaEnforcer.check_provision()`.

    `allow=False` plus a non-empty `reasons` list means the broker must
    reject the provision request. Each reason cites the binding scope so
    the operator can see whether it's a per-service or per-pack cap.

    `breakdown` always carries the current vs. max for every checked
    scope (even on allow) so the broker's response can show callers how
    much headroom they have."""

    allow: bool
    reasons: list[str] = Field(default_factory=list)
    breakdown: list[QuotaUsageEntry] = Field(default_factory=list)


class QuotaUsageEntry(BaseModel):
    """One (scope, used, max) tuple for a given tenant."""

    scope: str
    used_instances: int
    max_instances: int | None = None
    used_compute_units: float = 0.0
    max_compute_units: float | None = None
    period: Literal["monthly", "lifetime"] = "lifetime"

    @property
    def at_limit(self) -> bool:
        return (
            self.max_instances is not None
            and self.used_instances >= self.max_instances
        )


# Forward ref fixup for the model
QuotaCheckResult.model_rebuild()
