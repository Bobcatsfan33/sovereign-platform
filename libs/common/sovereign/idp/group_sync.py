"""Group-to-role sync.

When a JWT arrives with IdP group claims (e.g. `groups: ["sovereign-
program-teams", "irs-cade2-leads"]`), the chassis derives the chassis
roles the principal should hold and upserts RoleBinding records via
the RoleStore. Subsequent calls see those bindings via the standard
AuthzResolver path.

Default mapping is `tenancy.DEFAULT_GROUP_ROLE_MAP` (a literal match
on group name → Role). Operators override per-tenant by passing their
own mapping to `sync_groups_to_roles`.

Tenant assignment for synced bindings comes from the TokenUser's `tid`
claim by default; callers can override for the org-wide patterns that
some IdPs use (e.g. agency-wide "sovereign-platform-admins" group →
binding at the root tenant)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..tenancy import Role, RoleBinding, RoleStore, TokenUser
from ..tenancy.jwt_auth import DEFAULT_GROUP_ROLE_MAP

logger = logging.getLogger("sovereign.idp.group_sync")


def sync_groups_to_roles(
    user: TokenUser,
    *,
    role_store: RoleStore | None = None,
    default_tenant_id: str | None = None,
    group_role_map: dict[str, Role] | None = None,
    group_tenant_map: dict[str, str] | None = None,
    granted_by: str = "idp-sync",
) -> list[RoleBinding]:
    """Materialise the principal's IdP groups as RoleBinding records.

    `group_role_map` overrides the chassis default group→role mapping.
    `group_tenant_map` overrides where (which tenant) each group's
    binding is written; missing entries fall back to
    `user.tenant_id` (the `tid` claim) and then to `default_tenant_id`.
    Returns the list of written bindings (already persisted to the
    RoleStore). Groups with no Role mapping are skipped (logged at
    DEBUG)."""
    rs = role_store or RoleStore()
    role_map = group_role_map if group_role_map is not None else DEFAULT_GROUP_ROLE_MAP
    tenant_map = group_tenant_map or {}

    written: list[RoleBinding] = []
    for group in _unique(user.groups):
        role = role_map.get(group)
        if role is None:
            logger.debug("no role mapping for group %r; skipping", group)
            continue
        tenant_id = tenant_map.get(group) or user.tenant_id or default_tenant_id
        if not tenant_id:
            logger.warning(
                "group %r maps to role %s but no tenant_id available; skipping",
                group,
                role.value,
            )
            continue
        binding = RoleBinding(
            principal=user.principal,
            tenant_id=tenant_id,
            role=role,
            granted_by=granted_by,
            metadata={"source_group": group},
        )
        rs.put(binding)
        written.append(binding)
    return written


def _unique(items: Iterable[str]) -> list[str]:
    """Order-preserving uniq."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
