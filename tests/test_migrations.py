"""Tests for the payload schema versioning + migration framework (E4)."""

from __future__ import annotations

import pytest
from sovereign import migrations
from sovereign.migrations import SchemaMigrationError, migrate_payload


def test_legacy_payload_defaults_to_v1_and_is_stamped() -> None:
    """A row written before versioning has no schema_version; it is treated
    as v1 and stamped, without mutating the caller's dict."""
    raw = {"instance_id": "i-1"}
    out = migrate_payload(raw, kind="instance")
    assert out["schema_version"] == 1
    assert "schema_version" not in raw  # input untouched


def test_current_version_payload_is_passthrough() -> None:
    raw = {"instance_id": "i-1", "schema_version": 1}
    assert migrate_payload(raw, kind="instance") == raw


def test_migration_chain_runs_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def v1_to_v2(p: dict) -> dict:
        calls.append(1)
        return {**p, "b": p["a"] + 1}

    def v2_to_v3(p: dict) -> dict:
        calls.append(2)
        return {**p, "c": p["b"] + 1}

    monkeypatch.setitem(migrations.CURRENT_SCHEMA_VERSIONS, "widget", 3)
    monkeypatch.setitem(migrations._MIGRATIONS, "widget", {1: v1_to_v2, 2: v2_to_v3})

    out = migrate_payload({"a": 1, "schema_version": 1}, kind="widget")
    assert calls == [1, 2]
    assert out == {"a": 1, "b": 2, "c": 3, "schema_version": 3}


def test_partial_version_only_runs_remaining_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(migrations.CURRENT_SCHEMA_VERSIONS, "widget", 3)
    monkeypatch.setitem(
        migrations._MIGRATIONS,
        "widget",
        {1: lambda p: {**p, "b": 1}, 2: lambda p: {**p, "c": 1}},
    )
    out = migrate_payload({"schema_version": 2, "b": 0}, kind="widget")
    assert out == {"schema_version": 3, "b": 0, "c": 1}


def test_payload_newer_than_code_fails_closed() -> None:
    with pytest.raises(SchemaMigrationError, match="deploy the newer code first"):
        migrate_payload({"schema_version": 99}, kind="instance")


def test_missing_intermediate_migration_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(migrations.CURRENT_SCHEMA_VERSIONS, "widget", 3)
    monkeypatch.setitem(migrations._MIGRATIONS, "widget", {})  # no steps registered
    with pytest.raises(SchemaMigrationError, match="no migration registered"):
        migrate_payload({"schema_version": 1}, kind="widget")


def test_unknown_kind_raises() -> None:
    with pytest.raises(SchemaMigrationError, match="unknown record kind"):
        migrate_payload({}, kind="does-not-exist")


def test_register_migration_decorator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(migrations.CURRENT_SCHEMA_VERSIONS, "widget", 2)
    monkeypatch.setitem(migrations._MIGRATIONS, "widget", {})

    @migrations.register_migration("widget", from_version=1)
    def _up(p: dict) -> dict:
        return {**p, "migrated": True}

    out = migrate_payload({"schema_version": 1}, kind="widget")
    assert out["migrated"] is True
