"""OIDC token verifier using JWKS.

The chassis's Phase-3 baseline accepts HS256 tokens signed with a shared
secret (dev). Production deployments swap that for `OidcVerifier`:
- Read the provider's `/.well-known/openid-configuration`
- Pull the JWKS from the `jwks_uri`
- Verify RS256 (or ES256) tokens against the matching key

The verifier caches the discovery document + JWKS with a TTL so it
isn't fetched on every request. Cache is best-effort: on a fetch
failure mid-cache the old keys keep working until they expire.

A successful verify returns the raw claims dict. The caller (broker's
`identify`) turns those into a `TokenUser`.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

logger = logging.getLogger("sovereign.idp.oidc")


class OidcVerifier:
    """Stateless from the caller's point of view, internally caches the
    discovery + JWKS."""

    def __init__(
        self,
        issuer_url: str,
        *,
        audience: str | None = None,
        cache_ttl: float = 3600.0,
        http_timeout: float = 5.0,
        algorithms: tuple[str, ...] = ("RS256", "ES256"),
    ) -> None:
        self._issuer = issuer_url.rstrip("/")
        self._audience = audience
        self._cache_ttl = cache_ttl
        self._timeout = http_timeout
        self._algorithms = list(algorithms)

        self._lock = threading.Lock()
        self._discovery: dict[str, Any] | None = None
        self._discovery_loaded_at: float = 0.0
        self._jwks_client: PyJWKClient | None = None

    # ── public ────────────────────────────────────────────────────

    def verify(self, token: str) -> dict[str, Any]:
        """Decode + verify `token`. Raises jwt.InvalidTokenError on any
        failure (signature, audience, expiry, missing kid)."""
        jwks_client = self._get_jwks_client()
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token).key
        except Exception as exc:  # noqa: BLE001
            raise jwt.InvalidTokenError(f"unable to resolve signing key: {exc}") from exc

        # PyJWT verifies aud automatically when an audience is provided;
        # explicitly skip that check when no audience is configured.
        kwargs: dict[str, Any] = {
            "algorithms": self._algorithms,
            "issuer": self._issuer,
        }
        if self._audience is not None:
            kwargs["audience"] = self._audience
        else:
            kwargs["options"] = {"verify_aud": False}
        return jwt.decode(token, signing_key, **kwargs)

    # ── discovery + JWKS caching ──────────────────────────────────

    def _get_discovery(self) -> dict[str, Any]:
        with self._lock:
            fresh = (
                self._discovery is not None
                and (time.time() - self._discovery_loaded_at) < self._cache_ttl
            )
            if fresh and self._discovery is not None:
                return self._discovery
        # Network call outside the lock.
        url = f"{self._issuer}/.well-known/openid-configuration"
        try:
            r = httpx.get(url, timeout=self._timeout)
            r.raise_for_status()
            doc = r.json()
        except httpx.HTTPError as exc:
            with self._lock:
                if self._discovery is not None:
                    logger.warning(
                        "discovery refresh failed (%s); keeping cached document", exc
                    )
                    return self._discovery
            raise
        with self._lock:
            self._discovery = doc
            self._discovery_loaded_at = time.time()
            self._jwks_client = None  # invalidate so we rebuild against new jwks_uri
        return doc

    def _get_jwks_client(self) -> PyJWKClient:
        with self._lock:
            cached = self._jwks_client
        if cached is not None:
            return cached
        discovery = self._get_discovery()
        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise RuntimeError(f"{self._issuer}/.well-known/openid-configuration has no jwks_uri")
        client = PyJWKClient(jwks_uri, lifespan=int(self._cache_ttl))
        with self._lock:
            self._jwks_client = client
        return client

    # ── operator helpers ──────────────────────────────────────────

    def discovery(self) -> dict[str, Any]:
        """Return the cached (or freshly-fetched) discovery document.
        Useful for /healthz to show the issuer is reachable."""
        return self._get_discovery()
