"""Tests for the tenant hierarchy + RBAC model (Phase 3 tasks 3.1 + 3.2)."""

from __future__ import annotations

import pytest
from moto import mock_aws
from sovereign.tenancy import (
    AuthzResolver,
    Role,
    RoleBinding,
    RoleStore,
    Tenant,
    TenantLevel,
    TenantStore,
)
from sovereign.tenancy.models import (
    ACTION_MANAGE_QUOTAS,
    ACTION_PROVISION,
    ACTION_READ,
    ACTION_READ_AUDIT,
)

# ── Fixtures: build a realistic agency tree ───────────────────────────


def _build_treasury_tree(store: TenantStore) -> None:
    """Department of Treasury → IRS → IT Modernization → CADE2 + ECM
    plus IRS → Cybersecurity → CDM."""
    store.put(Tenant(tenant_id="treasury", name="Department of Treasury", level=TenantLevel.agency))
    store.put(
        Tenant(
            tenant_id="irs", name="IRS", level=TenantLevel.bureau, parent_id="treasury"
        )
    )
    store.put(
        Tenant(
            tenant_id="irs-it-mod",
            name="IT Modernization",
            level=TenantLevel.office,
            parent_id="irs",
        )
    )
    store.put(
        Tenant(
            tenant_id="cade2",
            name="CADE2",
            level=TenantLevel.program,
            parent_id="irs-it-mod",
        )
    )
    store.put(
        Tenant(
            tenant_id="ecm",
            name="Enterprise Case Management",
            level=TenantLevel.program,
            parent_id="irs-it-mod",
        )
    )
    store.put(
        Tenant(
            tenant_id="irs-cyber",
            name="Cybersecurity",
            level=TenantLevel.office,
            parent_id="irs",
        )
    )
    store.put(
        Tenant(
            tenant_id="cdm",
            name="CDM Implementation",
            level=TenantLevel.program,
            parent_id="irs-cyber",
        )
    )


# ── TenantStore ───────────────────────────────────────────────────────


def test_tenant_round_trip() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        store.put(Tenant(tenant_id="t1", name="T1", level=TenantLevel.agency))
        got = store.get("t1")
        assert got is not None
        assert got.name == "T1"
        assert got.level == TenantLevel.agency
        assert got.parent_id is None


def test_tenant_get_missing_returns_none() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        assert store.get("nope") is None


def test_tenant_get_children() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        _build_treasury_tree(store)
        irs_children = {t.tenant_id for t in store.get_children("irs")}
        assert irs_children == {"irs-it-mod", "irs-cyber"}


def test_tenant_get_ancestors_root_to_leaf() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        _build_treasury_tree(store)
        ancestors = [t.tenant_id for t in store.get_ancestors("cade2")]
        # immediate-parent first, root last
        assert ancestors == ["irs-it-mod", "irs", "treasury"]


def test_tenant_get_descendants_transitive() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        _build_treasury_tree(store)
        descendants = {t.tenant_id for t in store.get_descendants("irs")}
        assert descendants == {"irs-it-mod", "irs-cyber", "cade2", "ecm", "cdm"}


def test_tenant_is_ancestor_of() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        _build_treasury_tree(store)
        assert store.is_ancestor_of("treasury", "cade2") is True
        assert store.is_ancestor_of("irs", "cade2") is True
        assert store.is_ancestor_of("cade2", "irs") is False
        # Sibling check
        assert store.is_ancestor_of("cade2", "ecm") is False


def test_tenant_path_root_to_leaf() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        _build_treasury_tree(store)
        path = [t.tenant_id for t in store.path("cade2")]
        assert path == ["treasury", "irs", "irs-it-mod", "cade2"]


def test_tenant_delete() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        store.put(Tenant(tenant_id="t", name="T", level=TenantLevel.program))
        store.delete("t")
        assert store.get("t") is None


def test_tenant_ensure_table_idempotent() -> None:
    with mock_aws():
        store = TenantStore()
        store.ensure_table()
        store.ensure_table()


# ── RoleStore ─────────────────────────────────────────────────────────


def test_role_binding_round_trip() -> None:
    with mock_aws():
        store = RoleStore()
        store.ensure_table()
        store.put(
            RoleBinding(principal="alice@gov", tenant_id="cade2", role=Role.program_team)
        )
        got = store.get("alice@gov", "cade2")
        assert got is not None
        assert got.role == Role.program_team


def test_roles_for_principal_returns_all_bindings() -> None:
    with mock_aws():
        store = RoleStore()
        store.ensure_table()
        store.put(RoleBinding(principal="bob", tenant_id="irs", role=Role.bureau_admin))
        store.put(RoleBinding(principal="bob", tenant_id="cade2", role=Role.program_team))
        bindings = store.roles_for("bob")
        assert {b.tenant_id for b in bindings} == {"irs", "cade2"}


def test_roles_for_tenant_returns_all_principals() -> None:
    with mock_aws():
        store = RoleStore()
        store.ensure_table()
        store.put(RoleBinding(principal="alice", tenant_id="cade2", role=Role.program_team))
        store.put(RoleBinding(principal="bob", tenant_id="cade2", role=Role.auditor))
        bindings = store.roles_for_tenant("cade2")
        principals = {b.principal for b in bindings}
        assert principals == {"alice", "bob"}


def test_principals_with_role() -> None:
    with mock_aws():
        store = RoleStore()
        store.ensure_table()
        store.put(RoleBinding(principal="alice", tenant_id="cade2", role=Role.program_team))
        store.put(RoleBinding(principal="bob", tenant_id="ecm", role=Role.program_team))
        store.put(RoleBinding(principal="carol", tenant_id="cade2", role=Role.auditor))
        program_team = {b.principal for b in store.principals_with_role(Role.program_team)}
        assert program_team == {"alice", "bob"}


def test_role_delete() -> None:
    with mock_aws():
        store = RoleStore()
        store.ensure_table()
        store.put(RoleBinding(principal="alice", tenant_id="cade2", role=Role.program_team))
        store.delete("alice", "cade2")
        assert store.get("alice", "cade2") is None


# ── AuthzResolver ─────────────────────────────────────────────────────


@pytest.fixture
def resolver_with_treasury():  # type: ignore[no-untyped-def]
    """A ready-to-use AuthzResolver with the treasury tree seeded plus
    a small set of role bindings. Tests assert behaviour without each
    re-building the tree."""
    with mock_aws():
        tenants = TenantStore()
        tenants.ensure_table()
        _build_treasury_tree(tenants)

        roles = RoleStore()
        roles.ensure_table()
        # alice: program-team on CADE2
        roles.put(RoleBinding(principal="alice", tenant_id="cade2", role=Role.program_team))
        # bob: bureau-admin on IRS (inherits down)
        roles.put(RoleBinding(principal="bob", tenant_id="irs", role=Role.bureau_admin))
        # carol: agency-admin on treasury
        roles.put(RoleBinding(principal="carol", tenant_id="treasury", role=Role.agency_admin))
        # dave: auditor on IRS
        roles.put(RoleBinding(principal="dave", tenant_id="irs", role=Role.auditor))
        # eve: platform-admin on root (granted at treasury)
        roles.put(RoleBinding(principal="eve", tenant_id="treasury", role=Role.platform_admin))

        yield AuthzResolver(tenants=tenants, roles=roles)


def test_program_member_can_provision_their_program(resolver_with_treasury):  # type: ignore[no-untyped-def]
    e = resolver_with_treasury.effective_roles_at("alice", "cade2")
    assert Role.program_team in e.roles
    assert e.can(ACTION_PROVISION)


def test_program_member_cannot_see_sibling_program(resolver_with_treasury):  # type: ignore[no-untyped-def]
    e = resolver_with_treasury.effective_roles_at("alice", "ecm")
    assert not e.roles
    assert not e.can(ACTION_READ)


def test_bureau_admin_inherits_down_to_program(resolver_with_treasury):  # type: ignore[no-untyped-def]
    e = resolver_with_treasury.effective_roles_at("bob", "cade2")
    assert Role.bureau_admin in e.roles
    assert e.can(ACTION_PROVISION)
    assert "irs" in e.inherited_from


def test_agency_admin_inherits_to_every_descendant(
    resolver_with_treasury,
):  # type: ignore[no-untyped-def]
    e = resolver_with_treasury.effective_roles_at("carol", "cdm")
    assert Role.agency_admin in e.roles


def test_auditor_can_read_audit_not_provision(resolver_with_treasury):  # type: ignore[no-untyped-def]
    e = resolver_with_treasury.effective_roles_at("dave", "cade2")
    assert e.can(ACTION_READ)
    assert e.can(ACTION_READ_AUDIT)
    assert not e.can(ACTION_PROVISION)


def test_platform_admin_holds_global_access(resolver_with_treasury):  # type: ignore[no-untyped-def]
    # Even at a tenant where they hold no direct binding (cdm), the
    # platform-admin binding at treasury grants full access.
    e = resolver_with_treasury.effective_roles_at("eve", "cdm")
    assert Role.platform_admin in e.roles
    assert e.can(ACTION_MANAGE_QUOTAS)


def test_can_shortcut(resolver_with_treasury):  # type: ignore[no-untyped-def]
    assert resolver_with_treasury.can("alice", "cade2", ACTION_PROVISION)
    assert not resolver_with_treasury.can("alice", "cdm", ACTION_PROVISION)


def test_visible_tenants_program_sees_only_self(resolver_with_treasury):  # type: ignore[no-untyped-def]
    visible = resolver_with_treasury.visible_tenants("alice", "cade2")
    assert visible == ["cade2"]


def test_visible_tenants_bureau_admin_sees_descendants(
    resolver_with_treasury,
):  # type: ignore[no-untyped-def]
    visible = set(resolver_with_treasury.visible_tenants("bob", "irs"))
    # bob is bureau-admin on irs -> sees irs plus every descendant
    assert visible == {"irs", "irs-it-mod", "irs-cyber", "cade2", "ecm", "cdm"}


def test_visible_tenants_no_role_returns_empty(resolver_with_treasury):  # type: ignore[no-untyped-def]
    visible = resolver_with_treasury.visible_tenants("nobody", "cade2")
    assert visible == []


def test_visible_tenants_auditor_sees_descendants(resolver_with_treasury):  # type: ignore[no-untyped-def]
    visible = set(resolver_with_treasury.visible_tenants("dave", "irs"))
    # auditor scope mirrors bureau-admin's visibility (read-only)
    assert "cade2" in visible
    assert "cdm" in visible
