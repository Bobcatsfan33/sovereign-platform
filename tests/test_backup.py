"""Tests for the DynamoDB backup / restore drill (E4)."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws


def _seed_store() -> None:
    from sovereign.models import Binding, LbParameters, ServiceInstance
    from sovereign.store import Store

    store = Store()
    store.ensure_tables()
    store.put_instance(
        ServiceInstance(
            instance_id="i-1",
            service_id="sovereign-envoy-lb",
            plan_id="standard-regional",
            organization_guid="org-1",
            parameters=LbParameters(),
        )
    )
    store.put_binding(Binding(binding_id="b-1", instance_id="i-1", credentials={"k": "v"}))


def _local_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    from sovereign import settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "dynamodb_endpoint", None)
    monkeypatch.setattr(settings_module.Settings, "s3_endpoint", None)
    settings_module.get_settings.cache_clear()


@mock_aws
def test_export_restore_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_aws(monkeypatch)
    from sovereign.backup import (
        export_snapshot,
        read_snapshot_from_s3,
        restore_snapshot,
        write_snapshot_to_s3,
    )
    from sovereign.store import Store

    _seed_store()

    snap = export_snapshot()
    assert len(snap["tables"]["sovereign_instances"]) == 1
    assert len(snap["tables"]["sovereign_bindings"]) == 1

    # Durable round trip through S3.
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="backups")
    write_snapshot_to_s3("backups", "snap.json", snap)
    restored = read_snapshot_from_s3("backups", "snap.json")
    assert restored["tables"]["sovereign_instances"][0]["instance_id"] == "i-1"

    # Simulate data loss, then restore.
    store = Store()
    store.delete_instance("i-1")
    store.delete_binding("b-1")
    assert store.get_instance("i-1") is None

    counts = restore_snapshot(restored)
    assert counts == {"sovereign_instances": 1, "sovereign_bindings": 1}
    recovered = store.get_instance("i-1")
    assert recovered is not None and recovered.organization_guid == "org-1"
    assert store.get_binding("b-1") is not None


@mock_aws
def test_run_drill_reports_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_aws(monkeypatch)
    from sovereign.backup import run_drill

    _seed_store()
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="backups")

    result = run_drill("backups", "drill.json")
    assert result["ok"] is True
    assert result["counts"] == {"sovereign_instances": 1, "sovereign_bindings": 1}


@mock_aws
def test_restore_only_selected_table(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_aws(monkeypatch)
    from sovereign.backup import export_snapshot, restore_snapshot
    from sovereign.store import Store

    _seed_store()
    snap = export_snapshot()

    store = Store()
    store.delete_instance("i-1")
    store.delete_binding("b-1")

    counts = restore_snapshot(snap, only=("sovereign_bindings",))
    assert counts == {"sovereign_bindings": 1}
    assert store.get_instance("i-1") is None  # not restored
    assert store.get_binding("b-1") is not None
