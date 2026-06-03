"""Tests for OIDC verifier + group-to-role sync (Phase 3 task 3.5)."""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws
from sovereign.idp import OidcVerifier, sync_groups_to_roles
from sovereign.tenancy import (
    Role,
    RoleStore,
    TokenUser,
)

# ── OIDC verifier ─────────────────────────────────────────────────────


def _make_rsa_keypair() -> tuple[Any, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def _rsa_jwk(public_key: Any, kid: str = "test-key") -> dict[str, Any]:
    """Produce a JWKS entry for the public key."""
    from jwt.algorithms import RSAAlgorithm

    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return jwk


def _mock_oidc_responses(
    discovery_url: str,
    jwks_uri: str,
    jwks: dict[str, Any],
    *,
    jwks_cache_control: str | None = None,
) -> object:
    """Return an httpx mock function that responds to discovery + JWKS."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(discovery_url):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://idp.test",
                    "jwks_uri": jwks_uri,
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if str(request.url).startswith(jwks_uri):
            headers = {"cache-control": jwks_cache_control} if jwks_cache_control else {}
            return httpx.Response(200, json=jwks, headers=headers)
        return httpx.Response(404, text=str(request.url))

    return httpx.MockTransport(handler)


def _install_mock_transport(transport: object) -> object:
    """Patch httpx.get + PyJWKClient's internal httpx.Client to use the
    same MockTransport. Returns the active patcher object so callers can
    stop() it in a finally."""
    import httpx

    # PyJWKClient uses urllib by default — for test isolation we patch
    # the OidcVerifier path (httpx.get for discovery) AND PyJWKClient's
    # url-fetch via the same module's urllib.request.urlopen.
    orig_get = httpx.get

    def patched_get(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        client = httpx.Client(transport=transport)  # type: ignore[arg-type]
        try:
            return client.get(url, *args, **kwargs)
        finally:
            client.close()

    httpx.get = patched_get  # type: ignore[assignment]
    return orig_get


def test_oidc_verifier_round_trip_with_mocked_jwks() -> None:
    private_key, public_key = _make_rsa_keypair()
    jwks = {"keys": [_rsa_jwk(public_key, kid="k1")]}

    discovery_url = "https://idp.test/.well-known/openid-configuration"
    jwks_uri = "https://idp.test/oauth2/jwks"
    transport = _mock_oidc_responses(discovery_url, jwks_uri, jwks)

    # Mint a token signed by the private key
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = jwt.encode(
        {
            "iss": "https://idp.test",
            "sub": "alice@gov",
            "aud": "sovereign-broker",
            "exp": int(time.time()) + 60,
            "groups": ["sovereign-program-teams"],
        },
        pem,
        algorithm="RS256",
        headers={"kid": "k1"},
    )

    # Patch httpx.get (discovery) AND PyJWKClient's url-fetch path.
    orig_get = _install_mock_transport(transport)
    try:
        verifier = OidcVerifier(
            issuer_url="https://idp.test", audience="sovereign-broker"
        )
        claims = verifier.verify(token)
        assert claims["sub"] == "alice@gov"
        assert claims["groups"] == ["sovereign-program-teams"]
    finally:
        import httpx

        httpx.get = orig_get  # type: ignore[assignment]


def test_oidc_verifier_rejects_wrong_audience() -> None:
    private_key, public_key = _make_rsa_keypair()
    jwks = {"keys": [_rsa_jwk(public_key, kid="k1")]}
    transport = _mock_oidc_responses(
        "https://idp.test/.well-known/openid-configuration",
        "https://idp.test/oauth2/jwks",
        jwks,
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = jwt.encode(
        {
            "iss": "https://idp.test",
            "sub": "alice",
            "aud": "wrong-audience",
            "exp": int(time.time()) + 60,
        },
        pem,
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    orig_get = _install_mock_transport(transport)
    try:
        verifier = OidcVerifier(
            issuer_url="https://idp.test", audience="expected-audience"
        )
        with pytest.raises(jwt.InvalidAudienceError):
            verifier.verify(token)
    finally:
        import httpx

        httpx.get = orig_get  # type: ignore[assignment]


def test_oidc_verifier_discovery_no_jwks_uri_raises() -> None:
    import httpx

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issuer": "https://idp.test"})

    orig_get = _install_mock_transport(httpx.MockTransport(handler))
    try:
        verifier = OidcVerifier(issuer_url="https://idp.test")
        with pytest.raises(RuntimeError, match="jwks_uri"):
            verifier._get_jwks_client()
    finally:
        httpx.get = orig_get  # type: ignore[assignment]


def test_oidc_verifier_honors_jwks_max_age() -> None:
    private_key, public_key = _make_rsa_keypair()
    jwks = {"keys": [_rsa_jwk(public_key, kid="k1")]}
    transport = _mock_oidc_responses(
        "https://idp.test/.well-known/openid-configuration",
        "https://idp.test/oauth2/jwks",
        jwks,
        jwks_cache_control="public, max-age=42",
    )
    orig_get = _install_mock_transport(transport)
    try:
        verifier = OidcVerifier(issuer_url="https://idp.test", cache_ttl=3600)
        assert verifier._fetch_jwks_data() == jwks
        assert verifier._jwks_ttl == 42
    finally:
        import httpx

        httpx.get = orig_get  # type: ignore[assignment]


def test_oidc_verifier_uses_stale_jwks_within_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    jwks = {"keys": [{"kid": "k1"}]}
    verifier = OidcVerifier(
        issuer_url="https://idp.test",
        cache_ttl=10,
        stale_grace=30,
    )
    verifier._discovery = {"jwks_uri": "https://idp.test/oauth2/jwks"}
    verifier._discovery_loaded_at = time.time()
    verifier._jwks_data = jwks
    verifier._jwks_loaded_at = time.time() - 11
    verifier._jwks_ttl = 10

    def unavailable(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("idp down")

    monkeypatch.setattr(httpx, "get", unavailable)

    assert verifier._fetch_jwks_data() == jwks


def test_oidc_verifier_rejects_stale_jwks_after_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    verifier = OidcVerifier(
        issuer_url="https://idp.test",
        cache_ttl=10,
        stale_grace=30,
    )
    verifier._discovery = {"jwks_uri": "https://idp.test/oauth2/jwks"}
    verifier._discovery_loaded_at = time.time()
    verifier._jwks_data = {"keys": [{"kid": "k1"}]}
    verifier._jwks_loaded_at = time.time() - 45
    verifier._jwks_ttl = 10

    def unavailable(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("idp down")

    monkeypatch.setattr(httpx, "get", unavailable)

    with pytest.raises(httpx.ConnectError):
        verifier._fetch_jwks_data()


# ── Group sync ────────────────────────────────────────────────────────


def test_sync_groups_to_roles_uses_default_mapping() -> None:
    with mock_aws():
        rs = RoleStore()
        rs.ensure_table()
        user = TokenUser(
            principal="alice@gov",
            tenant_id="cade2",
            groups=("sovereign-program-teams", "ignore-me"),
            raw={},
        )
        written = sync_groups_to_roles(user, role_store=rs)
        assert len(written) == 1
        assert written[0].role == Role.program_team
        assert written[0].tenant_id == "cade2"
        # The unmapped group was silently skipped.

        # Round-trips through the store.
        got = rs.get("alice@gov", "cade2")
        assert got is not None
        assert got.role == Role.program_team
        assert got.granted_by == "idp-sync"
        assert got.metadata["source_group"] == "sovereign-program-teams"


def test_sync_groups_to_roles_custom_mapping() -> None:
    with mock_aws():
        rs = RoleStore()
        rs.ensure_table()
        user = TokenUser(
            principal="bob@gov",
            tenant_id="irs",
            groups=("irs-cade2-leads",),
            raw={},
        )
        written = sync_groups_to_roles(
            user,
            role_store=rs,
            group_role_map={"irs-cade2-leads": Role.program_team},
            group_tenant_map={"irs-cade2-leads": "cade2"},
        )
        assert len(written) == 1
        assert written[0].tenant_id == "cade2"  # overridden, not 'irs'


def test_sync_groups_to_roles_skips_when_no_tenant() -> None:
    with mock_aws():
        rs = RoleStore()
        rs.ensure_table()
        user = TokenUser(
            principal="carol@gov",
            tenant_id=None,
            groups=("sovereign-platform-admins",),
            raw={},
        )
        # No tenant_id on the token, no group_tenant override, no default
        # -> binding is skipped (logged WARNING).
        written = sync_groups_to_roles(user, role_store=rs)
        assert written == []


def test_sync_groups_to_roles_uniqs_duplicates() -> None:
    with mock_aws():
        rs = RoleStore()
        rs.ensure_table()
        user = TokenUser(
            principal="dave@gov",
            tenant_id="cade2",
            groups=(
                "sovereign-program-teams",
                "sovereign-program-teams",  # duplicate
                "sovereign-auditors",
            ),
            raw={},
        )
        written = sync_groups_to_roles(user, role_store=rs)
        # 2 distinct roles even though the input had a dupe.
        assert {b.role for b in written} == {Role.program_team, Role.auditor}


def test_sync_groups_to_roles_default_tenant_fallback() -> None:
    with mock_aws():
        rs = RoleStore()
        rs.ensure_table()
        user = TokenUser(principal="x", tenant_id=None, groups=("sovereign-auditors",), raw={})
        written = sync_groups_to_roles(user, role_store=rs, default_tenant_id="treasury")
        assert len(written) == 1
        assert written[0].tenant_id == "treasury"
