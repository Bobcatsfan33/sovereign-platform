"""Quota enforcer — combine QuotaStore + UsageStore to gate provision.

Two callsites:

  - `check_provision(tenant_id, service_type, pack)` — broker calls
    this BEFORE running the policy / renderer. Returns
    `QuotaCheckResult` whose `allow=False` rejects with a clear reason.

  - `usage_summary(tenant_id)` — broker /v2/usage/{tenant_id} returns
    every (scope, used, max) tuple so callers can see headroom.

Counting is done at query time off the metering service's Usage records
(resource_type='instance', metadata.service_type matches). For Phase 3
the volumes are small enough that the per-request scan is fine; the
obvious upgrade is a per-(tenant, scope) counter in DynamoDB that the
provision path increments atomically.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from ..usage_store import UsageStore
from .models import (
    Quota,
    QuotaCheckResult,
    QuotaUsageEntry,
    pack_scope,
    service_type_scope,
)
from .store import QuotaStore


class QuotaEnforcer:
    def __init__(
        self,
        quotas: QuotaStore | None = None,
        usage: UsageStore | None = None,
    ) -> None:
        self._quotas = quotas or QuotaStore()
        self._usage = usage or UsageStore()

    # ── public API ──────────────────────────────────────────────────

    def check_provision(
        self,
        *,
        tenant_id: str,
        service_type: str,
        pack: str | None = None,
    ) -> QuotaCheckResult:
        """Gate a provision request against the tenant's quotas.

        Checks the per-service-type quota AND (if `pack` is given) the
        pack-rollup quota. Either being at-cap rejects. If neither
        quota is configured for the tenant, the request is allowed —
        the chassis ships permissive by default; operators tighten by
        writing quotas via the QuotaStore."""
        per_service = self._compute_usage(
            tenant_id, service_type_scope(service_type), counting_service_type=service_type
        )
        entries = [per_service]
        reasons: list[str] = []

        if per_service.at_limit:
            reasons.append(
                f"quota: tenant {tenant_id!r} at the per-service cap for "
                f"{service_type!r} ({per_service.used_instances}/"
                f"{per_service.max_instances})"
            )

        if pack:
            per_pack = self._compute_usage(
                tenant_id, pack_scope(pack), counting_service_type=None, counting_pack=pack
            )
            entries.append(per_pack)
            if per_pack.at_limit:
                reasons.append(
                    f"quota: tenant {tenant_id!r} at the per-pack cap for "
                    f"{pack!r} ({per_pack.used_instances}/{per_pack.max_instances})"
                )

        return QuotaCheckResult(allow=not reasons, reasons=reasons, breakdown=entries)

    def usage_summary(self, tenant_id: str) -> list[QuotaUsageEntry]:
        """Return one QuotaUsageEntry per (tenant, scope) — both for
        scopes that have a configured Quota AND for service-type scopes
        seen in the metering record stream but never bounded.

        The breakdown is the data the GET /v2/usage/{tenant_id} route
        surfaces — tenant admins use it to see headroom, budget systems
        use it for chargeback."""
        configured = self._quotas.list_for_tenant(tenant_id)
        observed_scopes = self._observed_service_type_scopes(tenant_id)

        all_scopes: dict[str, Quota | None] = {q.scope: q for q in configured}
        for scope in observed_scopes:
            all_scopes.setdefault(scope, None)

        return [
            self._compute_usage(
                tenant_id, scope, counting_service_type=_service_type_from_scope(scope),
                counting_pack=_pack_from_scope(scope),
            )
            for scope in sorted(all_scopes)
        ]

    # ── internals ───────────────────────────────────────────────────

    def _compute_usage(
        self,
        tenant_id: str,
        scope: str,
        *,
        counting_service_type: str | None = None,
        counting_pack: str | None = None,
    ) -> QuotaUsageEntry:
        """Build a QuotaUsageEntry for one (tenant, scope) by:
          1. fetching the configured Quota if any (max_*)
          2. scanning metering records and counting matches"""
        quota = self._quotas.get(tenant_id, scope)
        records = self._usage.query(tenant_id=tenant_id, limit=1000)

        used_instances = 0
        used_compute = 0.0
        for r in records:
            if r.resource_type != "instance":
                continue
            md = r.metadata or {}
            if counting_service_type is not None and md.get("service_type") != counting_service_type:
                continue
            if counting_pack is not None and md.get("pack") != counting_pack:
                continue
            used_instances += 1
            used_compute += r.quantity or 0.0

        if counting_service_type is None and counting_pack is None and scope.startswith("service_type:"):
            # Fallback: scope was parseable as service_type but the caller
            # didn't pass an explicit filter — derive from the scope.
            svc = scope.removeprefix("service_type:")
            used_instances = sum(
                1
                for r in records
                if r.resource_type == "instance" and (r.metadata or {}).get("service_type") == svc
            )

        return QuotaUsageEntry(
            scope=scope,
            used_instances=used_instances,
            max_instances=quota.max_instances if quota else None,
            used_compute_units=used_compute,
            max_compute_units=quota.max_compute_units if quota else None,
            period=quota.period if quota else "lifetime",
        )

    def _observed_service_type_scopes(self, tenant_id: str) -> set[str]:
        """Service-type scopes seen in the metering record stream — so
        usage_summary can list service types the tenant has consumed even
        if no quota is configured (max_instances=None means unlimited but
        still counted for visibility)."""
        records = self._usage.query(tenant_id=tenant_id, limit=1000)
        observed: set[str] = set()
        for r in records:
            md = r.metadata or {}
            svc = md.get("service_type")
            if isinstance(svc, str) and svc:
                observed.add(service_type_scope(svc))
            pack = md.get("pack")
            if isinstance(pack, str) and pack:
                observed.add(pack_scope(pack))
        return observed


def _service_type_from_scope(scope: str) -> str | None:
    return scope.removeprefix("service_type:") if scope.startswith("service_type:") else None


def _pack_from_scope(scope: str) -> str | None:
    return scope.removeprefix("pack:") if scope.startswith("pack:") else None


# Silence unused-import warning while keeping the imports useful for
# downstream consumers who import these symbols from .enforcer.
_ = (datetime, UTC, timedelta, defaultdict)
