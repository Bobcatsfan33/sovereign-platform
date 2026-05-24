"""Tests for the service catalog model + DynamoDB store (Phase 1 task 1.7)."""

from __future__ import annotations

from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.catalog import (
    CatalogStore,
    ConnectorCatalogEntry,
    ParameterSchema,
    ServiceCatalogEntry,
    ServicePlan,
)
from sovereign.connectors.github import GitHubConnector
from sovereign.connectors.s3 import S3Connector
from sovereign.renderers.envoy import EnvoyRenderer


def _service_entry() -> ServiceCatalogEntry:
    return ServiceCatalogEntry(
        service_type="test-svc",
        name="test-svc",
        description="A test service.",
        plans=[
            ServicePlan(id="small", name="small", description="Small."),
            ServicePlan(id="large", name="large", description="Large.", free=False),
        ],
        parameter_schema=ParameterSchema(
            schema={"type": "object", "properties": {"x": {"type": "string"}}}
        ),
        tags=["test"],
        pack="testpack",
    )


def _connector_entry() -> ConnectorCatalogEntry:
    return ConnectorCatalogEntry(
        connector_type="test-conn",
        name="test-conn",
        description="A test connector.",
        capabilities=["list"],
    )


# ── CatalogStore round-trips ──────────────────────────────────────────


def test_catalog_store_round_trip_service() -> None:
    with mock_aws():
        store = CatalogStore()
        store.ensure_table()
        entry = _service_entry()
        store.put_service(entry)

        got = store.get_service("test-svc")
        assert got is not None
        assert got.service_type == "test-svc"
        assert {p.id for p in got.plans} == {"small", "large"}
        assert got.parameter_schema.schema_["properties"]["x"]["type"] == "string"
        assert got.tags == ["test"]
        assert got.pack == "testpack"


def test_catalog_store_round_trip_connector() -> None:
    with mock_aws():
        store = CatalogStore()
        store.ensure_table()
        entry = _connector_entry()
        store.put_connector(entry)

        got = store.get_connector("test-conn")
        assert got is not None
        assert got.connector_type == "test-conn"
        assert "list" in got.capabilities


def test_catalog_list_returns_only_matching_kind() -> None:
    with mock_aws():
        store = CatalogStore()
        store.ensure_table()
        store.put_service(_service_entry())
        store.put_connector(_connector_entry())

        services = store.list_services()
        connectors = store.list_connectors()
        assert {s.service_type for s in services} == {"test-svc"}
        assert {c.connector_type for c in connectors} == {"test-conn"}


def test_catalog_get_missing_returns_none() -> None:
    with mock_aws():
        store = CatalogStore()
        store.ensure_table()
        assert store.get_service("missing") is None
        assert store.get_connector("missing") is None


def test_catalog_delete() -> None:
    with mock_aws():
        store = CatalogStore()
        store.ensure_table()
        store.put_service(_service_entry())
        store.delete("service", "test-svc")
        assert store.get_service("test-svc") is None


def test_catalog_ensure_table_idempotent() -> None:
    with mock_aws():
        store = CatalogStore()
        store.ensure_table()
        store.ensure_table()  # second call must not error


def test_catalog_query_failure_raises_runtime_error() -> None:
    # Without moto active and without a real table, the query fails
    # under botocore's NoCredentials/NoRegion path.
    with mock_aws():
        store = CatalogStore()
        # Don't call ensure_table — table missing -> ClientError -> RuntimeError
        with pytest.raises(RuntimeError, match="catalog query failed"):
            store.list_services()


# ── catalog_entry() classmethods on chassis components ────────────────


def test_envoy_renderer_catalog_entry_shape() -> None:
    e = EnvoyRenderer.catalog_entry()
    assert e is not None
    assert e.service_type == "sovereign-envoy-lb"
    plan_ids = {p.id for p in e.plans}
    assert plan_ids == {"standard-regional", "multi-region", "sidecar"}
    # Parameter schema is a real JSON Schema with structure.
    schema = e.parameter_schema.schema_
    assert schema["type"] == "object"
    assert "listeners" in schema["properties"]
    assert "clusters" in schema["properties"]


def test_s3_connector_catalog_entry_shape() -> None:
    e = S3Connector.catalog_entry()
    assert e is not None
    assert e.connector_type == "s3"
    assert "ingest" in e.capabilities
    # Config schema enumerates the two cred kinds (oneOf).
    one_of = e.config_schema.schema_.get("oneOf", [])
    kinds = {choice["properties"]["kind"]["const"] for choice in one_of}
    assert kinds == {"aws_access_key", "aws_iam_role"}


def test_github_connector_catalog_entry_shape() -> None:
    e = GitHubConnector.catalog_entry()
    assert e is not None
    assert e.connector_type == "github"
    assert e.config_schema.schema_["properties"]["kind"]["const"] == "github_pat"


# ── End-to-end: broker /v2/catalog reads from CatalogStore ────────────


@pytest.fixture
def broker_with_seeded_catalog(broker_module: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The broker_module fixture loads broker/app/main, which imports
    the renderers + connectors (side-effect registration). The startup
    hook then seeds the catalog. We just need outbound stubs for
    render() / audit / policy so provision tests still work without a
    real control plane / OPA."""
    from sovereign.models import PolicyDecision

    class FakeAudit:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

    class FakePolicy:
        def evaluate(self, _input: Any) -> PolicyDecision:
            return PolicyDecision(allow=True, denies=[], matched_layers=[])

    monkeypatch.setattr(broker_module, "audit", FakeAudit())
    monkeypatch.setattr(broker_module, "policy", FakePolicy())
    return broker_module


@mock_aws
def test_v2_catalog_returns_seeded_service_and_connector_entries(
    broker_with_seeded_catalog: Any,
) -> None:
    with TestClient(broker_with_seeded_catalog.app) as client:
        r = client.get("/v2/catalog", auth=("broker", "broker"))
        assert r.status_code == 200, r.text
        body = r.json()
        # Services
        svc_ids = {s["id"] for s in body["services"]}
        assert "sovereign-envoy-lb" in svc_ids
        lb = next(s for s in body["services"] if s["id"] == "sovereign-envoy-lb")
        assert {p["id"] for p in lb["plans"]} == {
            "standard-regional",
            "multi-region",
            "sidecar",
        }
        # parameter_schema surfaced with the actual JSON Schema body
        assert "schema" in lb["parameter_schema"]
        assert "listeners" in lb["parameter_schema"]["schema"]["properties"]
        # Tags + pack metadata present
        assert "network" in lb["tags"]
        assert lb["metadata"]["pack"] == "chassis"

        # Connectors (chassis: s3 + github)
        conn_ids = {c["id"] for c in body["connectors"]}
        assert {"s3", "github"} <= conn_ids
        s3 = next(c for c in body["connectors"] if c["id"] == "s3")
        assert "ingest" in s3["capabilities"]


@mock_aws
def test_v2_catalog_falls_back_to_live_registries_when_store_empty(
    broker_with_seeded_catalog: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate the catalog table being missing (no ensure_table) by
    pointing the CatalogStore at a non-existent table just before the
    HTTP call. The route should degrade to the live registry entries
    rather than 5xx."""
    bm = broker_with_seeded_catalog
    # Make list_services raise to exercise the except branch.
    monkeypatch.setattr(
        bm.catalog,
        "list_services",
        lambda: (_ for _ in ()).throw(RuntimeError("table missing")),
    )
    monkeypatch.setattr(
        bm.catalog,
        "list_connectors",
        lambda: (_ for _ in ()).throw(RuntimeError("table missing")),
    )
    with TestClient(bm.app) as client:
        r = client.get("/v2/catalog", auth=("broker", "broker"))
        assert r.status_code == 200
        body = r.json()
        # Fallback still surfaces the LB plus the two connectors.
        svc_ids = {s["id"] for s in body["services"]}
        assert "sovereign-envoy-lb" in svc_ids
        conn_ids = {c["id"] for c in body["connectors"]}
        assert {"s3", "github"} <= conn_ids


# Suppress unused-import noise
_ = boto3
