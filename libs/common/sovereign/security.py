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


#: Header the chassis uses to assert/verify a workload identity (mirrors the
#: inbound `require_bearer` alias). A real mesh/front-door may instead inject
#: `X-SPIFFE-ID`; the inbound side accepts either.
WORKLOAD_IDENTITY_HEADER = "X-Sovereign-Workload-Identity"


def service_auth_headers() -> dict[str, str]:
    """Build outbound auth headers for a service-to-service call (E2).

    Symmetric with the inbound `require_bearer` policy so the platform can
    talk to itself under every auth posture:

    - When workload identity is enabled, assert this service's identity in
      the workload-identity header (what the inbound side verifies first).
    - When the shared bearer is still enabled (dev/transition posture), also
      include the Bearer token so a peer that has not enabled workload
      identity yet keeps accepting the call.

    In the locked-down production posture (workload identity on, shared bearer
    off) this yields an identity header and no token — exactly what the
    hardened inbound path requires, and the reason the platform previously
    could not call itself in production."""
    s = get_settings()
    headers: dict[str, str] = {}
    if s.workload_identity_enabled:
        headers[WORKLOAD_IDENTITY_HEADER] = s.asserted_workload_identity()
    if s.shared_bearer_auth_enabled:
        headers["Authorization"] = f"Bearer {s.dev_bearer_token}"
    return headers


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
