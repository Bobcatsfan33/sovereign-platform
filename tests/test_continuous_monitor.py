"""Tests for the continuous monitoring CLI (Phase 5 task 5.2)."""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parent.parent
MONITOR_PATH = ROOT / "scripts" / "continuous_monitor.py"


def load_monitor() -> Any:
    spec = importlib.util.spec_from_file_location("continuous_monitor", str(MONITOR_PATH))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["continuous_monitor"] = module
    spec.loader.exec_module(module)
    return module


# ── check_opa_policy_tests ───────────────────────────────────────────


def test_opa_policy_tests_passes_on_green_bundle() -> None:
    """If `opa` is installed locally, the chassis bundle must pass at
    100% coverage. Skipped in CI runners that don't install opa for
    the pytest job."""
    import shutil

    if shutil.which("opa") is None:
        pytest.skip("opa binary not on PATH; the dedicated policy-test job covers this")
    monitor = load_monitor()
    result = monitor.check_opa_policy_tests()
    assert result.ok, result.detail
    assert "CA-7" in result.nist_controls
    assert "CM-7" in result.nist_controls


# ── check_audit_freshness ────────────────────────────────────────────


def test_audit_freshness_skips_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUDIT_SERVICE_URL", raising=False)
    monitor = load_monitor()
    result = monitor.check_audit_freshness()
    assert result.status == "SKIP"
    assert "AUDIT_SERVICE_URL" in result.detail


def test_audit_freshness_pass_when_events_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIT_SERVICE_URL", "http://audit.test")
    monkeypatch.setenv("SOVEREIGN_BEARER_TOKEN", "x")

    monitor = load_monitor()

    def fake_get(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
        assert "/events" in url
        assert "since=" in url
        assert headers["Authorization"] == "Bearer x"
        return 200, b'{"count": 12, "events": []}'

    monkeypatch.setattr(monitor, "_http_get", fake_get)
    result = monitor.check_audit_freshness()
    assert result.status == "PASS"
    assert "12 event" in result.detail


def test_audit_freshness_fail_on_zero_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIT_SERVICE_URL", "http://audit.test")
    monitor = load_monitor()
    monkeypatch.setattr(monitor, "_http_get", lambda *_a, **_kw: (200, b'{"count": 0, "events": []}'))
    result = monitor.check_audit_freshness()
    assert result.status == "FAIL"
    assert "no audit events" in result.detail


def test_audit_freshness_fail_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIT_SERVICE_URL", "http://audit.test")
    monitor = load_monitor()
    monkeypatch.setattr(monitor, "_http_get", lambda *_a, **_kw: (503, b"down"))
    result = monitor.check_audit_freshness()
    assert result.status == "FAIL"
    assert "503" in result.detail


# ── check_image_scan_freshness ───────────────────────────────────────


def test_image_scan_freshness_skips_when_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    result = monitor.check_image_scan_freshness()
    assert result.status == "SKIP"


def test_image_scan_freshness_pass_when_recent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    reports = tmp_path / ".trivy-reports"
    reports.mkdir()
    for svc in ("broker", "control-plane", "audit-service", "metering-service", "portal"):
        (reports / f"{svc}.timestamp").touch()
    result = monitor.check_image_scan_freshness()
    assert result.status == "PASS"
    assert "5 chassis image" in result.detail


def test_image_scan_freshness_fail_when_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    reports = tmp_path / ".trivy-reports"
    reports.mkdir()
    stale = reports / "broker.timestamp"
    stale.touch()
    # Backdate by 5 days
    old = (datetime.now(UTC) - timedelta(days=5)).timestamp()
    os.utime(stale, (old, old))
    result = monitor.check_image_scan_freshness(max_age_hours=24)
    assert result.status == "FAIL"
    assert "scanned > 24h ago" in result.detail


def test_image_scan_freshness_fail_when_dir_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    (tmp_path / ".trivy-reports").mkdir()
    result = monitor.check_image_scan_freshness()
    assert result.status == "FAIL"
    assert "no scan timestamps" in result.detail


# ── check_settings_sentinels ─────────────────────────────────────────


def test_settings_sentinels_skip_outside_prod() -> None:
    monitor = load_monitor()
    from sovereign.settings import Settings, get_settings

    get_settings.cache_clear()
    with patch.object(Settings, "env", "dev"):
        result = monitor.check_settings_sentinels()
    assert result.status == "SKIP"


def test_settings_sentinels_fail_when_dev_token_active_in_prod() -> None:
    monitor = load_monitor()
    from sovereign.settings import Settings, get_settings

    get_settings.cache_clear()
    with patch.object(Settings, "env", "production"), patch.object(
        Settings, "dev_bearer_token", "dev-token"
    ):
        result = monitor.check_settings_sentinels()
    assert result.status == "FAIL"
    assert "dev_bearer_token" in result.detail


def test_settings_sentinels_pass_when_real_secrets_injected() -> None:
    monitor = load_monitor()
    from sovereign.settings import Settings, get_settings

    get_settings.cache_clear()
    with patch.object(Settings, "env", "production"), patch.object(
        Settings, "dev_bearer_token", "real-token"
    ), patch.object(Settings, "broker_password", "real-pass"), patch.object(
        Settings, "s3_secret_key", "real-key"
    ), patch.object(Settings, "dev_jwt_secret", "real-secret"):
        result = monitor.check_settings_sentinels()
    assert result.status == "PASS"


# ── check_state_drift (with moto) ────────────────────────────────────


@mock_aws
def test_state_drift_passes_when_every_instance_has_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An instance in DynamoDB whose rendered config exists in S3 must reconcile."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.delenv("DYNAMODB_ENDPOINT", raising=False)

    from sovereign.models import LbParameters, ServiceInstance
    from sovereign.settings import get_settings
    from sovereign.store import Store

    get_settings.cache_clear()
    # Force endpoint_url=None so moto intercepts
    from sovereign import settings as settings_mod
    monkeypatch.setattr(settings_mod.Settings, "dynamodb_endpoint", None)
    monkeypatch.setattr(settings_mod.Settings, "s3_endpoint", None)
    monkeypatch.setattr(settings_mod.Settings, "s3_access_key", "test")
    monkeypatch.setattr(settings_mod.Settings, "s3_secret_key", "test")
    monkeypatch.setattr(settings_mod.Settings, "config_bucket", "test-bucket")

    store = Store()
    store.ensure_tables()
    inst = ServiceInstance(
        instance_id="i1",
        service_id="sovereign-envoy-lb",
        plan_id="standard-regional",
        organization_guid="agency-x",
        parameters=LbParameters(),
    )
    store.put_instance(inst)

    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    s3.put_object(Bucket="test-bucket", Key="instances/i1/v1/envoy.yaml", Body=b"placeholder")

    monitor = load_monitor()
    result = monitor.check_state_drift()
    assert result.ok, result.detail
    assert "reconcile cleanly" in result.detail


@mock_aws
def test_state_drift_fails_when_artifact_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    from sovereign import settings as settings_mod
    from sovereign.models import LbParameters, ServiceInstance
    from sovereign.store import Store

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "dynamodb_endpoint", None)
    monkeypatch.setattr(settings_mod.Settings, "s3_endpoint", None)
    monkeypatch.setattr(settings_mod.Settings, "config_bucket", "test-bucket-empty")

    store = Store()
    store.ensure_tables()
    store.put_instance(
        ServiceInstance(
            instance_id="orphan",
            service_id="sovereign-envoy-lb",
            plan_id="standard-regional",
            parameters=LbParameters(),
        )
    )

    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket-empty")
    # Intentionally no put_object — the instance has no rendered artifact.

    monitor = load_monitor()
    result = monitor.check_state_drift()
    assert result.status == "FAIL"
    assert "orphan@v1" in result.detail


# ── Runner ───────────────────────────────────────────────────────────


def test_main_exits_zero_when_all_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(
        monitor,
        "CHECKS",
        {"only": lambda: monitor.CheckResult("only", "PASS", "ok")},
    )
    code = monitor.main(["--check", "only"])
    assert code == 0


def test_main_exits_nonzero_on_any_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(
        monitor,
        "CHECKS",
        {
            "ok": lambda: monitor.CheckResult("ok", "PASS", "fine"),
            "broken": lambda: monitor.CheckResult("broken", "FAIL", "no"),
        },
    )
    code = monitor.main([])
    assert code == 1


def test_main_skips_dont_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(
        monitor,
        "CHECKS",
        {"skipped": lambda: monitor.CheckResult("skipped", "SKIP", "no env")},
    )
    code = monitor.main([])
    assert code == 0


def test_main_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monitor = load_monitor()
    monkeypatch.setattr(
        monitor,
        "CHECKS",
        {"x": lambda: monitor.CheckResult("x", "PASS", "ok", ("AU-2",))},
    )
    code = monitor.main(["--check", "x", "--format", "json"])
    out = capsys.readouterr().out
    assert code == 0
    import json
    parsed = json.loads(out)
    assert parsed[0]["status"] == "PASS"
    assert parsed[0]["nist_controls"] == ["AU-2"]
