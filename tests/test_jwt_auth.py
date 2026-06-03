"""Tests for the JWT FastAPI dependencies + the authorize helper (Phase 3 task 3.3)."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.tenancy import (
    AuthzResolver,
    Role,
    RoleBinding,
    RoleStore,
    Tenant,
    TenantLevel,
    TenantStore,
    TokenUser,
    authorize,
    mint_dev_token,
    require_user,
)
from sovereign.tenancy.models import ACTION_PROVISION, ACTION_READ_AUDIT

# ── require_user ──────────────────────────────────────────────────────


async def test_require_user_extracts_claims() -> None:
    token = mint_dev_token(
        sub="alice@gov", tenant_id="cade2", groups=("sovereign-program-teams",)
    )
    user = await require_user(authorization=f"Bearer {token}")
    assert user.principal == "alice@gov"
    assert user.tenant_id == "cade2"
    assert user.groups == ("sovereign-program-teams",)


async def test_require_user_missing_header_raises_401() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await require_user(authorization=None)
    assert exc.value.status_code == 401


async def test_require_user_wrong_scheme_raises_401() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await require_user(authorization="Basic abc")
    assert exc.value.status_code == 401


async def test_require_user_invalid_token_raises_401() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await require_user(authorization="Bearer not.a.jwt")
    assert exc.value.status_code == 401
    assert "invalid token" in exc.value.detail


def test_decode_rejects_dev_jwt_when_oidc_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException
    from sovereign import settings as settings_module
    from sovereign.tenancy import jwt_auth

    monkeypatch.setattr(settings_module.Settings, "oidc_issuer_url", "")
    monkeypatch.setattr(settings_module.Settings, "require_oidc", True)
    settings_module.get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        jwt_auth._decode("not-used")
    assert exc.value.status_code == 401
    assert "OIDC is required" in exc.value.detail


def test_decode_uses_oidc_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module
    from sovereign.tenancy import jwt_auth

    class FakeVerifier:
        def verify(self, token: str) -> dict[str, Any]:
            assert token == "oidc-token"
            return {"sub": "alice@gov", "tid": "cade2", "groups": ["team"]}

    monkeypatch.setattr(settings_module.Settings, "oidc_issuer_url", "https://idp.test")
    monkeypatch.setattr(settings_module.Settings, "oidc_audience", "sovereign")
    monkeypatch.setattr(settings_module.Settings, "require_oidc", True)
    monkeypatch.setattr(jwt_auth, "_oidc_verifier", lambda _issuer, _aud: FakeVerifier())
    settings_module.get_settings.cache_clear()

    claims = jwt_auth._decode("oidc-token")
    assert claims["sub"] == "alice@gov"
    assert claims["groups"] == ["team"]


async def test_require_user_expired_token_raises_401() -> None:
    from fastapi import HTTPException
    from sovereign.settings import get_settings

    # Mint a token that expired one second ago.
    s = get_settings()
    payload = {"sub": "alice", "exp": int(time.time()) - 1}
    expired = jwt.encode(payload, s.dev_jwt_secret, algorithm="HS256")

    with pytest.raises(HTTPException) as exc:
        await require_user(authorization=f"Bearer {expired}")
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail


async def test_require_user_missing_sub_raises_401() -> None:
    from fastapi import HTTPException
    from sovereign.settings import get_settings

    s = get_settings()
    no_sub = jwt.encode({"groups": []}, s.dev_jwt_secret, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        await require_user(authorization=f"Bearer {no_sub}")
    assert exc.value.status_code == 401
    assert "sub" in exc.value.detail


# ── authorize() helper ────────────────────────────────────────────────


def _build_resolver() -> AuthzResolver:
    tenants = TenantStore()
    tenants.ensure_table()
    tenants.put(Tenant(tenant_id="agency", name="A", level=TenantLevel.agency))
    tenants.put(
        Tenant(tenant_id="prog", name="P", level=TenantLevel.program, parent_id="agency")
    )

    roles = RoleStore()
    roles.ensure_table()
    roles.put(RoleBinding(principal="alice", tenant_id="prog", role=Role.program_team))
    roles.put(RoleBinding(principal="dave", tenant_id="agency", role=Role.auditor))
    return AuthzResolver(tenants=tenants, roles=roles)


@mock_aws
def test_authorize_allows_when_role_grants_action() -> None:
    resolver = _build_resolver()
    user = TokenUser(principal="alice", tenant_id="prog", groups=(), raw={})
    effective = authorize(user, tenant_id="prog", action=ACTION_PROVISION, resolver=resolver)
    assert Role.program_team in effective.roles


@mock_aws
def test_authorize_denies_when_role_missing() -> None:
    from fastapi import HTTPException

    resolver = _build_resolver()
    user = TokenUser(principal="alice", tenant_id="prog", groups=(), raw={})
    with pytest.raises(HTTPException) as exc:
        # alice is program_team on prog (which doesn't grant manage-quotas)
        # but does grant read; pick an action she doesn't have.
        authorize(user, tenant_id="prog", action="manage-quotas", resolver=resolver)
    assert exc.value.status_code == 403
    detail = exc.value.detail
    assert detail["action"] == "manage-quotas"
    assert detail["principal"] == "alice"
    assert "program-team" in detail["roles_held"]


@mock_aws
def test_authorize_audit_role_can_read_audit_but_not_provision() -> None:
    from fastapi import HTTPException

    resolver = _build_resolver()
    user = TokenUser(principal="dave", tenant_id="agency", groups=(), raw={})
    # auditor at the agency inherits down to prog
    effective = authorize(
        user, tenant_id="prog", action=ACTION_READ_AUDIT, resolver=resolver
    )
    assert Role.auditor in effective.roles
    with pytest.raises(HTTPException) as exc:
        authorize(user, tenant_id="prog", action=ACTION_PROVISION, resolver=resolver)
    assert exc.value.status_code == 403


# ── End-to-end with a tiny FastAPI app ────────────────────────────────


def _build_app(resolver_factory):  # type: ignore[no-untyped-def]
    app = FastAPI()

    @app.get("/me")
    async def me(user: TokenUser = Depends(require_user)) -> dict[str, Any]:
        return {"principal": user.principal, "tenant_id": user.tenant_id}

    @app.post("/provision/{tenant_id}")
    async def do_provision(
        tenant_id: str, user: TokenUser = Depends(require_user)
    ) -> dict[str, Any]:
        effective = authorize(
            user, tenant_id=tenant_id, action=ACTION_PROVISION, resolver=resolver_factory()
        )
        return {"ok": True, "roles": sorted(r.value for r in effective.roles)}

    return app


@mock_aws
def test_end_to_end_provision_allowed() -> None:
    resolver = _build_resolver()
    app = _build_app(lambda: resolver)
    token = mint_dev_token(sub="alice", tenant_id="prog")
    r = TestClient(app).post(
        "/provision/prog", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert "program-team" in r.json()["roles"]


@mock_aws
def test_end_to_end_provision_denied() -> None:
    resolver = _build_resolver()
    app = _build_app(lambda: resolver)
    token = mint_dev_token(sub="dave", tenant_id="agency")  # auditor only
    r = TestClient(app).post(
        "/provision/prog", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["action"] == "provision"


def test_mint_dev_token_with_extra_claims() -> None:
    token = mint_dev_token(sub="bob", extra={"roles": ["admin"], "iss": "test-idp"})
    decoded = jwt.decode(
        token,
        # Use the same secret the test conftest set
        __import__("sovereign.settings", fromlist=["get_settings"]).get_settings().dev_jwt_secret,
        algorithms=["HS256"],
    )
    assert decoded["sub"] == "bob"
    assert decoded["iss"] == "test-idp"
    assert decoded["roles"] == ["admin"]
