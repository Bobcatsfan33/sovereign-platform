"""Tests for the SLO recording + alerting rules (E5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sovereign.observability import install_metrics_endpoint

ROOT = Path(__file__).resolve().parent.parent


def _rule_groups() -> list[dict[str, Any]]:
    doc = next(
        d
        for d in yaml.safe_load_all((ROOT / "deploy" / "k8s" / "prometheus-rules.yaml").read_text())
        if d and d.get("kind") == "PrometheusRule"
    )
    return doc["spec"]["groups"]


def _all_rules() -> list[dict[str, Any]]:
    return [rule for group in _rule_groups() for rule in group["rules"]]


def test_recording_rules_present() -> None:
    records = {r["record"] for r in _all_rules() if "record" in r}
    assert {
        "sovereign:request_error_rate5m",
        "sovereign:request_availability5m",
        "sovereign:request_latency_p99_5m",
    }.issubset(records)


def test_alerts_present_with_severity() -> None:
    alerts = {r["alert"]: r for r in _all_rules() if "alert" in r}
    assert {
        "SovereignServiceDown",
        "SovereignErrorBudgetBurn",
        "SovereignErrorBudgetFastBurn",
        "SovereignHighLatencyP99",
    }.issubset(alerts)
    for spec in alerts.values():
        assert spec["labels"]["severity"] in {"warning", "critical"}
        assert spec["annotations"]["summary"]


def test_rules_reference_emitted_metrics() -> None:
    """Every base metric the rules build on must actually be exposed by the
    services — otherwise an SLO silently never fires."""
    exprs = " ".join(r["expr"] for r in _all_rules())

    app = FastAPI()

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    install_metrics_endpoint(app, service="probe")
    client = TestClient(app)
    client.get("/ok")
    exposed = client.get("/metrics").text

    for metric in (
        "sovereign_http_requests_total",
        "sovereign_http_request_duration_seconds_bucket",
        "sovereign_service_up",
    ):
        assert metric in exprs, f"{metric} not used by any rule"
        assert metric in exposed, f"{metric} not emitted by the services"
