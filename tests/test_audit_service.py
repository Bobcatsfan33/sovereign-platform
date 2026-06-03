"""Tests for the dedicated audit service (apps/audit-service)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sovereign.models import AuditEvent

from .conftest import AUTH_HEADER


@dataclass
class FakeQueryResult:
    result_rows: list[list[Any]]


@dataclass
class FakeClickHouseClient:
    """Stand-in for clickhouse_connect's client. Records inserts and
    answers queries from the recorded rows. The `fail_next_insert` flag
    lets a test simulate a transient ClickHouse failure."""

    rows: list[list[Any]] = field(default_factory=list)
    inserts: int = 0
    queries: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail_next_insert: bool = False
    fail_next_query: bool = False

    def insert(self, _table: str, rows: list[list[Any]], *, column_names: list[str]) -> None:
        if self.fail_next_insert:
            self.fail_next_insert = False
            raise RuntimeError("clickhouse down")
        self.inserts += 1
        self.rows.extend(rows)

    def query(self, _sql: str, *, parameters: dict[str, Any]) -> FakeQueryResult:
        if self.fail_next_query:
            self.fail_next_query = False
            raise RuntimeError("clickhouse query down")
        self.queries.append((_sql, parameters))
        # Pretend the WHERE clause matches everything for the simple cases the
        # tests exercise; the SUT's filtering correctness is exercised by the
        # query-string assertions in the tests rather than by simulating SQL.
        return FakeQueryResult(result_rows=list(reversed(self.rows)))

    def command(self, _sql: str) -> None:  # pragma: no cover - CREATE DATABASE/TABLE
        return None


@pytest.fixture
def audit_app(audit_service_module: Any) -> tuple[Any, FakeClickHouseClient]:
    """Inject a fake ClickHouse client and reset the in-process buffer."""
    fake = FakeClickHouseClient()
    audit_service_module._client = fake
    audit_service_module._table_ready = True
    audit_service_module._buffer.clear()
    audit_service_module._last_event_hash = None
    return audit_service_module.app, fake


def _event_body() -> dict[str, Any]:
    return AuditEvent(
        tenant_id="acme",
        actor="alice",
        action="instance.provisioned",
        resource="svc/demo",
        decision="allow",
        metadata={"plan_id": "standard-regional"},
    ).model_dump(mode="json")


class TestHealthz:
    def test_healthz_is_open(self, audit_app: tuple[Any, FakeClickHouseClient]) -> None:
        client = TestClient(audit_app[0])
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["service"] == "audit-service"
        assert body["clickhouse_connected"] is True


class TestRetention:
    def test_ttl_clause_uses_days(self, audit_service_module: Any) -> None:
        assert audit_service_module._ttl_clause(730) == "TTL ts + INTERVAL 730 DAY DELETE"

    def test_ttl_clause_can_be_disabled(self, audit_service_module: Any) -> None:
        assert audit_service_module._ttl_clause(0) == ""


class TestPostEvents:
    def test_requires_bearer(self, audit_app: tuple[Any, FakeClickHouseClient]) -> None:
        client = TestClient(audit_app[0])
        r = client.post("/events", json=_event_body())
        assert r.status_code == 401

    def test_persists_to_clickhouse(self, audit_app: tuple[Any, FakeClickHouseClient]) -> None:
        app, fake = audit_app
        client = TestClient(app)
        r = client.post("/events", json=_event_body(), headers=AUTH_HEADER)
        assert r.status_code == 202
        body = r.json()
        assert body["accepted"] is True
        assert body["persisted"] is True
        assert body["buffered"] is False
        assert fake.inserts == 1
        # row shape matches the SUT's column order
        assert len(fake.rows[0]) == 11
        assert fake.rows[0][7] is None
        assert len(fake.rows[0][8]) == 64
        assert fake.rows[0][9] is None
        assert fake.rows[0][10] is None

    def test_hash_chains_accepted_events(
        self, audit_app: tuple[Any, FakeClickHouseClient]
    ) -> None:
        app, fake = audit_app
        client = TestClient(app)
        first = _event_body()
        second = _event_body()
        second["resource"] = "svc/second"

        assert client.post("/events", json=first, headers=AUTH_HEADER).status_code == 202
        assert client.post("/events", json=second, headers=AUTH_HEADER).status_code == 202

        assert fake.rows[0][7] is None
        assert fake.rows[1][7] == fake.rows[0][8]
        assert fake.rows[0][8] != fake.rows[1][8]

    def test_exports_chained_event_to_siem(
        self,
        audit_app: tuple[Any, FakeClickHouseClient],
        audit_service_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app, _fake = audit_app
        sent: list[tuple[dict[str, Any], dict[str, str]]] = []

        class FakeResponse:
            status_code = 202

        class FakeHttpClient:
            def __init__(self, *, timeout: float) -> None:
                assert timeout == 1.0

            def __enter__(self) -> FakeHttpClient:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def post(
                self,
                url: str,
                *,
                json: dict[str, Any],
                headers: dict[str, str],
            ) -> FakeResponse:
                assert url == "http://siem.test/events"
                sent.append((json, headers))
                return FakeResponse()

        monkeypatch.setattr(
            audit_service_module,
            "get_settings",
            lambda: SimpleNamespace(
                clickhouse_database="sovereign_test",
                siem_webhook_url="http://siem.test/events",
                siem_webhook_token="secret",
                siem_webhook_timeout_seconds=1.0,
            ),
        )
        monkeypatch.setattr(audit_service_module.httpx, "Client", FakeHttpClient)

        r = TestClient(app).post("/events", json=_event_body(), headers=AUTH_HEADER)

        assert r.status_code == 202
        assert sent[0][1] == {"Authorization": "Bearer secret"}
        assert len(sent[0][0]["event_hash"]) == 64

    def test_buffers_when_clickhouse_unavailable(
        self, audit_service_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force _connect to return None so the SUT takes the buffering path.
        monkeypatch.setattr(audit_service_module, "_client", None)
        monkeypatch.setattr(audit_service_module, "_connect", lambda: None)
        audit_service_module._buffer.clear()
        client = TestClient(audit_service_module.app)
        r = client.post("/events", json=_event_body(), headers=AUTH_HEADER)
        assert r.status_code == 202
        assert r.json()["buffered"] is True
        assert r.json()["persisted"] is False
        assert len(audit_service_module._buffer) == 1
        audit_service_module._buffer.clear()

    def test_buffers_on_transient_insert_failure(
        self, audit_app: tuple[Any, FakeClickHouseClient]
    ) -> None:
        app, fake = audit_app
        fake.fail_next_insert = True
        client = TestClient(app)
        r = client.post("/events", json=_event_body(), headers=AUTH_HEADER)
        assert r.status_code == 202
        assert r.json()["buffered"] is True

    def test_validation_error_returns_422(
        self, audit_app: tuple[Any, FakeClickHouseClient]
    ) -> None:
        client = TestClient(audit_app[0])
        # Missing required 'action' field
        bad = {"resource": "svc/demo"}
        r = client.post("/events", json=bad, headers=AUTH_HEADER)
        assert r.status_code == 422


class TestGetEvents:
    def test_requires_bearer(self, audit_app: tuple[Any, FakeClickHouseClient]) -> None:
        client = TestClient(audit_app[0])
        r = client.get("/events")
        assert r.status_code == 401

    def test_returns_events_with_filters(
        self, audit_app: tuple[Any, FakeClickHouseClient]
    ) -> None:
        app, fake = audit_app
        client = TestClient(app)
        # Insert two events
        client.post("/events", json=_event_body(), headers=AUTH_HEADER)
        client.post("/events", json=_event_body(), headers=AUTH_HEADER)

        r = client.get(
            "/events",
            params={"tenant_id": "acme", "action": "instance.provisioned", "limit": 10},
            headers=AUTH_HEADER,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert "event_hash" in body["events"][0]
        # Verify the SUT built a parameterised SQL query with our filters.
        sql, params = fake.queries[-1]
        assert "tenant_id = {tenant_id:String}" in sql
        assert "action = {action:String}" in sql
        assert params["tenant_id"] == "acme"
        assert "LIMIT 10" in sql

    def test_503_when_clickhouse_unreachable(
        self, audit_service_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(audit_service_module, "_client", None)
        monkeypatch.setattr(audit_service_module, "_connect", lambda: None)
        client = TestClient(audit_service_module.app)
        r = client.get("/events", headers=AUTH_HEADER)
        assert r.status_code == 503

    def test_all_filter_columns_make_it_into_sql(
        self, audit_app: tuple[Any, FakeClickHouseClient]
    ) -> None:
        from datetime import datetime

        app, fake = audit_app
        client = TestClient(app)
        params = {
            "tenant_id": "acme",
            "actor": "alice",
            "action": "instance.provisioned",
            "resource": "svc/demo",
            "decision": "allow",
            "since": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            "until": datetime(2026, 12, 31, tzinfo=UTC).isoformat(),
        }
        r = client.get("/events", params=params, headers=AUTH_HEADER)
        assert r.status_code == 200
        sql, sql_params = fake.queries[-1]
        for key in ("tenant_id", "actor", "action", "resource", "decision", "since", "until"):
            assert key in sql_params

    def test_query_500_translates_to_503(
        self, audit_app: tuple[Any, FakeClickHouseClient]
    ) -> None:
        app, fake = audit_app
        fake.fail_next_query = True
        client = TestClient(app)
        r = client.get("/events", headers=AUTH_HEADER)
        assert r.status_code == 503


class TestConnectAndFlushBuffer:
    def test_connect_returns_none_when_clickhouse_import_fails(
        self, audit_service_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the import inside _connect to blow up so we exercise the
        # graceful-degradation branch.
        monkeypatch.setattr(audit_service_module, "_client", None)
        monkeypatch.setattr(audit_service_module, "_table_ready", False)

        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "clickhouse_connect":
                raise RuntimeError("no clickhouse")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        assert audit_service_module._connect() is None

    def test_buffer_drains_on_successful_insert(
        self, audit_app: tuple[Any, FakeClickHouseClient], audit_service_module: Any
    ) -> None:
        # Prime the buffer with a stale event, then post a new one and
        # verify both end up persisted in fake.rows.
        audit_service_module._buffer.append(
            AuditEvent(action="prior", resource="svc/x")
        )
        app, fake = audit_app
        client = TestClient(app)
        r = client.post("/events", json=_event_body(), headers=AUTH_HEADER)
        assert r.status_code == 202
        # 1 buffered + 1 fresh = 2 rows total
        assert len(fake.rows) == 2

    def test_buffer_requeue_on_flush_failure(
        self, audit_app: tuple[Any, FakeClickHouseClient], audit_service_module: Any
    ) -> None:
        # Buffer has a stale event; the buffer-flush itself fails, the
        # subsequent direct insert succeeds. The previously buffered
        # event should be re-queued so it isn't lost.
        audit_service_module._buffer.clear()
        audit_service_module._buffer.append(
            AuditEvent(action="prior", resource="svc/x")
        )
        app, fake = audit_app
        fake.fail_next_insert = True  # flush_buffer call fails
        client = TestClient(app)
        r = client.post("/events", json=_event_body(), headers=AUTH_HEADER)
        assert r.status_code == 202
        # The flush failed, then the direct insert ran. fake.fail_next_insert
        # was a one-shot, so the direct insert succeeded for the fresh event.
        # Outcome: 1 fresh row in fake.rows, 1 event back in buffer.
        assert len(fake.rows) == 1
        assert len(audit_service_module._buffer) == 1
