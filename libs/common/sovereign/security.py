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

from .idp import get_oidc_verifier
from .mtls import XFCC_HEADER, parse_xfcc_identity
from .settings import get_settings
from .tracing import outbound_trace_headers


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
    # Continue the distributed trace across the hop (E5/WS3). Every inter-
    # service call already routes through here, so propagating the trace here
    # makes the whole provisioning path one trace with no per-call-site work.
    headers.update(outbound_trace_headers())
    return headers


async def require_bearer(
    authorization: str | None = Header(default=None),
    workload_identity: str | None = Header(default=None, alias="X-Sovereign-Workload-Identity"),
    spiffe_id: str | None = Header(default=None, alias="X-SPIFFE-ID"),
    forwarded_client_cert: str | None = Header(default=None, alias=XFCC_HEADER),
) -> str:
    """FastAPI dependency. Returns the verified caller identity: an mTLS/
    workload identity, an OIDC `sub`, or (dev/test only) the synthetic
    `"shared-bearer"` principal. Raises 401/403 when auth is missing or
    invalid, 503 when no auth scheme is configured."""

    s = get_settings()

    # E2 mesh mTLS (hardened posture). The only trusted identity is the one
    # the mesh verified via mTLS and forwarded as XFCC; Envoy sanitises any
    # client-supplied copy, so this cannot be spoofed on a direct path. Plain
    # X-Sovereign-Workload-Identity / X-SPIFFE-ID headers are deliberately
    # ignored here because a caller can set them freely.
    if s.mtls_required:
        verified_identity = parse_xfcc_identity(forwarded_client_cert)
        if not verified_identity:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="mTLS client certificate required",
            )
        allowed = _allowed_workload_identities(s.allowed_workload_identities)
        if _workload_identity_allowed(verified_identity, allowed):
            return verified_identity
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="workload identity is not allowed",
        )

    asserted_identity = workload_identity or spiffe_id
    if s.workload_identity_enabled and asserted_identity:
        allowed = _allowed_workload_identities(s.allowed_workload_identities)
        if _workload_identity_allowed(asserted_identity, allowed):
            return asserted_identity
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="workload identity is not allowed",
        )

    # S-1 — OIDC bearer: the production path for human, CI, and portal callers.
    # When an issuer is configured (always true outside dev), a Bearer token is
    # verified against the IdP's JWKS and the real `sub` is returned — not a
    # synthetic stub. When OIDC is required but no token is presented, fail closed.
    if s.require_oidc or s.oidc_issuer_url:
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            try:
                claims = get_oidc_verifier().verify(token)
            except Exception as exc:  # noqa: BLE001 — any verify failure is a 401
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid or expired token",
                ) from exc
            subject = claims.get("sub")
            if not subject:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="token missing 'sub' claim",
                )
            return str(subject)
        if s.require_oidc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OIDC bearer token required",
                headers={"WWW-Authenticate": 'Bearer realm="sovereign-platform"'},
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
    # The shared-bearer path is a dev/test convenience; it carries no real
    # subject, so it returns a clearly-synthetic principal.
    return "shared-bearer"
