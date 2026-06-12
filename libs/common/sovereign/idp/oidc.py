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
import re
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

logger = logging.getLogger("sovereign.idp.oidc")


_MAX_AGE_RE = re.compile(r"(?:^|,\s*)max-age=(\d+)(?:\s*,|$)")


class _CachedJwksClient(PyJWKClient):
    def __init__(
        self,
        uri: str,
        fetcher: Callable[[], dict[str, Any]],
        *,
        lifespan: int,
    ) -> None:
        super().__init__(uri, lifespan=lifespan)
        self._fetcher = fetcher

    def fetch_data(self) -> Any:
        return self._fetcher()


class OidcVerifier:
    """Stateless from the caller's point of view, internally caches the
    discovery + JWKS."""

    def __init__(
        self,
        issuer_url: str,
        *,
        audience: str | None = None,
        cache_ttl: float = 3600.0,
        stale_grace: float = 900.0,
        http_timeout: float = 5.0,
        algorithms: tuple[str, ...] = ("RS256", "ES256"),
    ) -> None:
        self._issuer = issuer_url.rstrip("/")
        self._audience = audience
        self._cache_ttl = cache_ttl
        self._stale_grace = stale_grace
        self._timeout = http_timeout
        self._algorithms = list(algorithms)

        self._lock = threading.Lock()
        self._discovery: dict[str, Any] | None = None
        self._discovery_loaded_at: float = 0.0
        self._jwks_client: PyJWKClient | None = None
        self._jwks_data: dict[str, Any] | None = None
        self._jwks_loaded_at: float = 0.0
        self._jwks_ttl: float = cache_ttl

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

    def _cache_fresh(self, loaded_at: float, ttl: float) -> bool:
        return (time.time() - loaded_at) < ttl

    def _cache_stale_but_usable(self, loaded_at: float, ttl: float) -> bool:
        return (time.time() - loaded_at) < (ttl + self._stale_grace)

    def _response_max_age(self, response: httpx.Response) -> float | None:
        header = response.headers.get("cache-control", "")
        match = _MAX_AGE_RE.search(header)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _fetch_jwks_data(self) -> dict[str, Any]:
        discovery = self._get_discovery()
        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise RuntimeError(f"{self._issuer}/.well-known/openid-configuration has no jwks_uri")

        with self._lock:
            if self._jwks_data is not None and self._cache_fresh(
                self._jwks_loaded_at, self._jwks_ttl
            ):
                return self._jwks_data

        try:
            response = httpx.get(jwks_uri, timeout=self._timeout)
            response.raise_for_status()
            jwks = response.json()
            ttl = self._response_max_age(response) or self._cache_ttl
        except (httpx.HTTPError, ValueError) as exc:
            with self._lock:
                if self._jwks_data is not None and self._cache_stale_but_usable(
                    self._jwks_loaded_at, self._jwks_ttl
                ):
                    logger.warning(
                        "JWKS refresh failed (%s); using stale keys within grace window",
                        exc,
                    )
                    return self._jwks_data
            raise

        with self._lock:
            self._jwks_data = jwks
            self._jwks_loaded_at = time.time()
            self._jwks_ttl = ttl
        return jwks

    def _get_jwks_client(self) -> PyJWKClient:
        with self._lock:
            cached = self._jwks_client
        if cached is not None:
            return cached
        discovery = self._get_discovery()
        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise RuntimeError(f"{self._issuer}/.well-known/openid-configuration has no jwks_uri")
        client = _CachedJwksClient(
            jwks_uri,
            self._fetch_jwks_data,
            lifespan=max(1, int(self._cache_ttl)),
        )
        with self._lock:
            self._jwks_client = client
        return client

    # ── operator helpers ──────────────────────────────────────────

    def discovery(self) -> dict[str, Any]:
        """Return the cached (or freshly-fetched) discovery document.
        Useful for /healthz to show the issuer is reachable."""
        return self._get_discovery()


# ── Process-wide verifier (S-1) ───────────────────────────────────────

_verifier: OidcVerifier | None = None
_verifier_issuer: str | None = None
_verifier_lock = threading.Lock()


def get_oidc_verifier() -> OidcVerifier:
    """Return the process-wide verifier, (re)built from settings when the
    configured issuer changes. So `require_bearer` can verify OIDC tokens
    without each call site constructing (and re-fetching JWKS for) a verifier."""
    global _verifier, _verifier_issuer
    from ..settings import get_settings

    s = get_settings()
    with _verifier_lock:
        if _verifier is None or _verifier_issuer != s.oidc_issuer_url:
            _verifier = OidcVerifier(
                s.oidc_issuer_url,
                audience=s.oidc_audience or None,
                cache_ttl=s.oidc_jwks_cache_ttl_seconds,
                stale_grace=s.oidc_jwks_stale_grace_seconds,
            )
            _verifier_issuer = s.oidc_issuer_url
        return _verifier


def set_oidc_verifier(verifier: OidcVerifier) -> None:
    """Install a verifier (test hook / explicit registration)."""
    global _verifier, _verifier_issuer
    from ..settings import get_settings

    with _verifier_lock:
        _verifier = verifier
        _verifier_issuer = get_settings().oidc_issuer_url


def reset_oidc_verifier() -> None:
    global _verifier, _verifier_issuer
    with _verifier_lock:
        _verifier = None
        _verifier_issuer = None
