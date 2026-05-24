"""JWT extraction + FastAPI dependencies for tenant-aware authorization.

Phase 3 task 3.3. The chassis accepts a Bearer JWT on every state-
changing endpoint. The token carries:

    sub:    principal identifier (OIDC sub claim — agency IdP)
    tid:    requested tenant id ("cade2", "irs", ...)
    groups: list of IdP groups (mapped to roles by 3.5's IdP layer)

For Phase 3 we accept HS256 tokens signed with a shared secret (the
DEV_JWT_SECRET env var). Phase 3.5 swaps in JWKS-based verification
against a real IdP without changing this module's signature.

Token issuance is out of scope for the chassis — `tools/mint_jwt.py`
ships a dev helper, and the IdP integration in 3.5 hands the broker
back tokens signed by the agency provider.

Usage in a FastAPI route::

    @router.put(...)
    def provision(req: ..., user: TokenUser = Depends(require_user)) -> ...:
        require_action(user, tenant_id="cade2", action="provision")
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, status

from ..settings import get_settings
from .authz import AuthzResolver, EffectiveAuthz
from .models import Role

JWT_ALGORITHMS = ["HS256"]


@dataclass(frozen=True)
class TokenUser:
    """Identity extracted from a verified JWT."""

    principal: str
    tenant_id: str | None
    groups: tuple[str, ...]
    raw: dict


def _decode(token: str) -> dict:
    s = get_settings()
    try:
        return jwt.decode(token, s.dev_jwt_secret, algorithms=JWT_ALGORITHMS)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {exc}"
        ) from exc


async def require_user(
    authorization: str | None = Header(default=None),
) -> TokenUser:
    """FastAPI dependency that returns the authenticated TokenUser.

    Accepts `Authorization: Bearer <jwt>`. Other auth schemes (HTTP
    Basic for OSB compatibility) are handled by their own dependencies
    upstream of this one."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="sovereign-platform"'},
        )
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ").strip()
    claims = _decode(token)
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing 'sub' claim"
        )
    return TokenUser(
        principal=str(sub),
        tenant_id=claims.get("tid"),
        groups=tuple(claims.get("groups", []) or []),
        raw=claims,
    )


def authorize(
    user: TokenUser,
    *,
    tenant_id: str,
    action: str,
    resolver: AuthzResolver,
) -> EffectiveAuthz:
    """Enforce that `user` can perform `action` at `tenant_id`. Raises
    HTTP 403 with a structured detail when the check fails; returns the
    EffectiveAuthz so callers can record the resolved roles for audit."""
    effective = resolver.effective_roles_at(user.principal, tenant_id)
    if not effective.can(action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "principal lacks the role required for this action",
                "principal": user.principal,
                "tenant_id": tenant_id,
                "action": action,
                "roles_held": sorted(r.value for r in effective.roles),
            },
        )
    return effective


def mint_dev_token(
    *,
    sub: str,
    tenant_id: str | None = None,
    groups: tuple[str, ...] = (),
    extra: dict | None = None,
) -> str:
    """Helper for local dev + tests — sign a JWT with the shared dev
    secret. Production callers must NOT use this; tokens come from the
    real IdP via 3.5's flow."""
    s = get_settings()
    payload: dict = {"sub": sub, "groups": list(groups)}
    if tenant_id:
        payload["tid"] = tenant_id
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.dev_jwt_secret, algorithm="HS256")


# Map of IdP group prefixes -> chassis Role. The 3.5 IdP layer reads
# `user.groups` and persists matching bindings via RoleStore — this map
# is the bridge between IdP-side and chassis-side role names. Operators
# override by writing per-tenant bindings directly to the RoleStore.
DEFAULT_GROUP_ROLE_MAP: dict[str, Role] = {
    "sovereign-platform-admins": Role.platform_admin,
    "sovereign-agency-admins": Role.agency_admin,
    "sovereign-bureau-admins": Role.bureau_admin,
    "sovereign-program-teams": Role.program_team,
    "sovereign-auditors": Role.auditor,
}
