"""Authorization resolver — what can this principal do at this tenant?

Combines the TenantStore (org tree) and RoleStore (bindings) to answer
two questions:

  * `effective_roles_at(principal, tenant_id)` — every role the principal
    holds at `tenant_id`, including roles inherited from ancestor tenants.
    A binding at an ancestor IS the same binding at the descendant; this
    is the inheritance rule that lets a bureau-admin manage every program
    in their bureau without an explicit binding per program.

  * `can(principal, tenant_id, action)` — boolean shortcut over the
    chassis's DEFAULT_ROLE_ACTIONS map.

The resolver is also the source of truth for the policy-input shape:
`scope(principal, tenant_id)` returns the set of tenant ids the principal
can SEE (the requested tenant plus every descendant) so the broker can
trim list responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DEFAULT_ROLE_ACTIONS, Role
from .role_store import RoleStore
from .tenant_store import TenantStore


@dataclass(frozen=True)
class EffectiveAuthz:
    """A read-only snapshot of what a principal can do at a tenant."""

    principal: str
    tenant_id: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    inherited_from: dict[str, frozenset[Role]] = field(default_factory=dict)

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def actions(self) -> frozenset[str]:
        out: set[str] = set()
        for role in self.roles:
            out |= DEFAULT_ROLE_ACTIONS.get(role, set())
        return frozenset(out)

    def can(self, action: str) -> bool:
        return action in self.actions()


class AuthzResolver:
    def __init__(self, tenants: TenantStore | None = None, roles: RoleStore | None = None) -> None:
        self._tenants = tenants or TenantStore()
        self._roles = roles or RoleStore()

    def effective_roles_at(self, principal: str, tenant_id: str) -> EffectiveAuthz:
        # 1. Direct bindings at this tenant.
        direct = {b.role for b in self._roles.roles_for(principal) if b.tenant_id == tenant_id}

        # 2. Bindings on every ancestor (inherited downward).
        inherited: dict[str, set[Role]] = {}
        for ancestor in self._tenants.get_ancestors(tenant_id):
            anc_roles = {
                b.role
                for b in self._roles.roles_for(principal)
                if b.tenant_id == ancestor.tenant_id
            }
            if anc_roles:
                inherited[ancestor.tenant_id] = anc_roles

        # 3. Platform-admin is a special case — a binding anywhere grants
        # global access. (A platform-admin binding is normally placed at
        # a special "*" or root tenant; we honour it wherever it lives.)
        for binding in self._roles.roles_for(principal):
            if binding.role == Role.platform_admin and binding.tenant_id != tenant_id:
                inherited.setdefault(binding.tenant_id, set()).add(Role.platform_admin)

        all_roles = set(direct)
        for s in inherited.values():
            all_roles |= s

        return EffectiveAuthz(
            principal=principal,
            tenant_id=tenant_id,
            roles=frozenset(all_roles),
            inherited_from={tid: frozenset(rs) for tid, rs in inherited.items()},
        )

    def can(self, principal: str, tenant_id: str, action: str) -> bool:
        return self.effective_roles_at(principal, tenant_id).can(action)

    def visible_tenants(self, principal: str, tenant_id: str) -> list[str]:
        """Every tenant id the principal can SEE starting from `tenant_id`.

        If the principal holds any role that grants `read` at the tenant
        AND that role is one of the admin roles, they also see every
        descendant. Program-team only sees its own tenant. Auditor sees
        the tenant plus descendants (read-only scope)."""
        effective = self.effective_roles_at(principal, tenant_id)
        if not effective.can("read"):
            return []

        admin_or_audit = {
            Role.platform_admin,
            Role.agency_admin,
            Role.bureau_admin,
            Role.auditor,
        }
        if effective.roles & admin_or_audit:
            descendants = self._tenants.get_descendants(tenant_id)
            return [tenant_id, *(d.tenant_id for d in descendants)]
        return [tenant_id]
