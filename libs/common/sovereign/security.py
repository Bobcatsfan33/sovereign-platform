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


async def require_bearer(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency. Returns the caller identity (currently a stub
    `"dev-user"` — replaced with a real subject claim once OIDC lands in
    Phase 3). Raises 401 if the token is missing, 403 if it mismatches."""

    token = get_settings().dev_bearer_token
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
