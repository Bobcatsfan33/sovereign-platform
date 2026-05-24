"""Pydantic models for tenants and role bindings.

The tenant tree mirrors government organizational structure:

    Agency (Department of Treasury)
      Bureau (IRS)
        Office (IT Modernization)
          Program (CADE2)

Each level is a Tenant with a `parent_id` pointing at its container.
The root nodes (Agencies) have `parent_id = None`. The chassis does
not enforce that the levels are strictly Agency->Bureau->Office->Program
because some agencies have intermediate organizations the standard
four-level model does not capture; the level is descriptive metadata
that drives display and reporting, not policy.

Roles bind a principal (a user, typically an OIDC `sub` claim) to a
tenant with a specific role. A single principal can hold multiple
bindings — e.g. bureau-admin of IRS plus program-team of CADE2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TenantLevel(StrEnum):
    agency = "agency"
    bureau = "bureau"
    office = "office"
    program = "program"


class Tenant(BaseModel):
    """A node in the tenant tree."""

    tenant_id: str
    name: str
    level: TenantLevel
    parent_id: str | None = None
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Role(StrEnum):
    platform_admin = "platform-admin"
    agency_admin = "agency-admin"
    bureau_admin = "bureau-admin"
    program_team = "program-team"
    auditor = "auditor"


# Action constants used by the AuthzResolver. Free strings are fine —
# this set is the chassis baseline; packs can extend it.
ACTION_PROVISION = "provision"
ACTION_DEPROVISION = "deprovision"
ACTION_UPDATE = "update"
ACTION_BIND = "bind"
ACTION_READ = "read"
ACTION_READ_AUDIT = "read-audit"
ACTION_MANAGE_TENANT = "manage-tenant"
ACTION_MANAGE_ROLES = "manage-roles"
ACTION_MANAGE_QUOTAS = "manage-quotas"


# Default role -> allowed-actions mapping for the chassis. The AuthzResolver
# uses this if a tenant has no per-tenant overrides.
DEFAULT_ROLE_ACTIONS: dict[Role, set[str]] = {
    Role.platform_admin: {
        ACTION_PROVISION,
        ACTION_DEPROVISION,
        ACTION_UPDATE,
        ACTION_BIND,
        ACTION_READ,
        ACTION_READ_AUDIT,
        ACTION_MANAGE_TENANT,
        ACTION_MANAGE_ROLES,
        ACTION_MANAGE_QUOTAS,
    },
    Role.agency_admin: {
        ACTION_PROVISION,
        ACTION_DEPROVISION,
        ACTION_UPDATE,
        ACTION_BIND,
        ACTION_READ,
        ACTION_READ_AUDIT,
        ACTION_MANAGE_TENANT,
        ACTION_MANAGE_ROLES,
        ACTION_MANAGE_QUOTAS,
    },
    Role.bureau_admin: {
        ACTION_PROVISION,
        ACTION_DEPROVISION,
        ACTION_UPDATE,
        ACTION_BIND,
        ACTION_READ,
        ACTION_READ_AUDIT,
        ACTION_MANAGE_ROLES,
        ACTION_MANAGE_QUOTAS,
    },
    Role.program_team: {
        ACTION_PROVISION,
        ACTION_DEPROVISION,
        ACTION_UPDATE,
        ACTION_BIND,
        ACTION_READ,
    },
    Role.auditor: {
        ACTION_READ,
        ACTION_READ_AUDIT,
    },
}


class RoleBinding(BaseModel):
    """Assigns `principal` the role `role` at `tenant_id`.

    Role inheritance: a role at an ancestor tenant grants the same role
    at every descendant tenant. So agency_admin of "treasury" implicitly
    holds agency_admin on every bureau/office/program under treasury;
    only the binding at the agency need be persisted."""

    principal: str
    tenant_id: str
    role: Role
    granted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    granted_by: str = "system"
    metadata: dict[str, Any] = Field(default_factory=dict)
