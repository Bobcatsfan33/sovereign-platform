"""Tenant hierarchy + RBAC for hierarchical government structure.

Models the Agency / Bureau / Office / Program org tree plus the role
bindings that drive authorization. Stored in DynamoDB so it's available
to every chassis service.

Public surface::

    from sovereign.tenancy import (
        Tenant, TenantLevel, TenantStore,
        Role, RoleBinding, RoleStore,
        EffectiveAuthz, AuthzResolver,
    )
"""

from .authz import AuthzResolver, EffectiveAuthz
from .jwt_auth import (
    DEFAULT_GROUP_ROLE_MAP,
    TokenUser,
    authorize,
    mint_dev_token,
    require_user,
)
from .models import Role, RoleBinding, Tenant, TenantLevel
from .role_store import RoleStore
from .tenant_store import TenantStore

__all__ = [
    "DEFAULT_GROUP_ROLE_MAP",
    "AuthzResolver",
    "EffectiveAuthz",
    "Role",
    "RoleBinding",
    "RoleStore",
    "Tenant",
    "TenantLevel",
    "TenantStore",
    "TokenUser",
    "authorize",
    "mint_dev_token",
    "require_user",
]
