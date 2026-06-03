"""Shared bearer-token authentication dependency.

A single, consistent auth pattern across every service in the base chassis.
Ported from sovereign-ai-broker's `require_bearer` so that audit, metering,
policy, broker, and control-plane all enforce the same scheme.

The token is loaded from the `DEV_BEARER_TOKEN` environment variable. In
production the token is provisioned by the secret manager, not hard-coded —
this default exists only so local docker-compose works out of the box.
"""

import secrets

from fastapi import Header, HTTPException, status

from .settings import get_settings


def _allowed_workload_identities(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def _workload_identity_allowed(identity: str, allowed: set[str]) -> bool:
    return "*" in allowed or identity in allowed


async def require_bearer(
    authorization: str | None = Header(default=None),
    workload_identity: str | None = Header(default=None, alias="X-Sovereign-Workload-Identity"),
    spiffe_id: str | None = Header(default=None, alias="X-SPIFFE-ID"),
) -> str:
    """FastAPI dependency. Returns the caller identity (currently a stub
    `"dev-user"` — replaced with a real subject claim once OIDC lands in
    Phase 3). Raises 401 if the token is missing, 403 if it mismatches."""

    s = get_settings()
    asserted_identity = workload_identity or spiffe_id
    if s.workload_identity_enabled and asserted_identity:
        allowed = _allowed_workload_identities(s.allowed_workload_identities)
        if _workload_identity_allowed(asserted_identity, allowed):
            return asserted_identity
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="workload identity is not allowed",
        )

    if not s.shared_bearer_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="shared bearer auth is disabled; configure workload identity",
        )

    token = s.dev_bearer_token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="sovereign-platform"'},
        )
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid token",
        )
    return "dev-user"
