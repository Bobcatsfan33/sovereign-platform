"""Per-tenant quota + chargeback (Phase 3 tasks 3.4 + 3.6).

Quotas are keyed by (tenant_id, scope) where scope is either
'service_type:<name>' or 'pack:<name>'. Provision is rejected when
EITHER the service-type quota OR the pack quota for that service is at
the cap.

Usage attribution flows through the existing metering service:
every successful provision emits a Usage record with
`resource_type='instance'` and the service_type in metadata. The
QuotaEnforcer aggregates those records per (tenant, scope) to compute
the current count.

Public surface::

    from sovereign.quotas import (
        Quota, QuotaCheckResult,
        service_type_scope, pack_scope,
        QuotaStore,
        QuotaEnforcer,
    )
"""

from .enforcer import QuotaEnforcer
from .models import Quota, QuotaCheckResult, pack_scope, service_type_scope
from .store import QuotaStore

__all__ = [
    "Quota",
    "QuotaCheckResult",
    "QuotaEnforcer",
    "QuotaStore",
    "pack_scope",
    "service_type_scope",
]
