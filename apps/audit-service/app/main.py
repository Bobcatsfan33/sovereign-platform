"""Dedicated audit service.

Phase 0 task 0.2 of the Sovereign Platform roadmap. Extracted from
`sovereign-ai-broker/apps/audit-pipeline/` and re-pointed at the fabric's
existing ClickHouse instance. The previous fabric pattern had every
service (broker, control-plane) writing to ClickHouse inline; that
coupling meant any ClickHouse degradation would surface as broker
failure. This service is the single ingestion point — services emit
events via HTTP and the service handles buffering + persistence.

Endpoints
---------
GET  /healthz                — liveness, unauthenticated.
POST /events                 — ingest one AuditEvent. Bearer auth.
GET  /events                 — query events. Bearer auth. Filters:
                                 tenant_id, actor, action, resource,
                                 decision, since, until, limit.

Graceful degradation
--------------------
If ClickHouse is unreachable, accepted events are appended to an in-process
ring buffer (capped). Each successful insert drains buffered events first.
This lets upstream callers stay non-blocking even during a short ClickHouse
outage; the failure mode is bounded memory loss after the cap is reached,
which is logged.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sovereign.audit_spool import AuditSpool
from sovereign.cors import install_cors
from sovereign.models import AuditEvent
from sovereign.ratelimit import install_rate_limit
from sovereign.security import require_bearer
from sovereign.settings import get_settings

logger = logging.getLogger("audit-service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Sovereign Platform — Audit Service", version="0.2.0")
install_cors(app)
install_rate_limit(app)

# ── ClickHouse client (lazy, with graceful degradation) ───────────────

_BUFFER_CAP = 1000
_buffer: deque[AuditEvent] = deque(maxlen=_BUFFER_CAP)
_buffer_lock = threading.Lock()
_client_lock = threading.Lock()
_client: Any = None  # clickhouse_connect.driver.Client | None — typed loosely to avoid hard import at module load
_table_ready = False

_spool: AuditSpool | None = (
    AuditSpool(get_settings().audit_spool_path) if get_settings().audit_spool_path else None
)


def _buffer_or_spool(event: AuditEvent) -> str:
    """Append to the in-memory buffer; when it is full, spill to the
    durable disk spool instead of letting the deque silently drop the
    oldest event (S5). Last resort (no spool configured) preserves the
    prior bounded-loss behaviour but logs an error."""
    with _buffer_lock:
        if len(_buffer) < _BUFFER_CAP:
            _buffer.append(event)
            return "buffer"
    if _spool is not None and _spool.append(event):
        return "spool"
    with _buffer_lock:
        _buffer.append(event)
    logger.error("audit buffer full and no durable spool; oldest event dropped")
    return "dropped"


def _connect() -> Any:
    """Return a ClickHouse client, creating database + table if needed.
    Returns None if ClickHouse is unreachable (caller falls back to buffer)."""
    global _client, _table_ready
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client
        try:
            import clickhouse_connect

            s = get_settings()
            client = clickhouse_connect.get_client(host=s.clickhouse_host, port=s.clickhouse_port)
            client.command(f"CREATE DATABASE IF NOT EXISTS {s.clickhouse_database}")
            client.command(
                f"""
                CREATE TABLE IF NOT EXISTS {s.clickhouse_database}.audit_events (
                  ts DateTime64(3),
                  tenant_id String,
                  actor String,
                  action String,
                  resource String,
                  decision String,
                  metadata String
                ) ENGINE = MergeTree
                ORDER BY (ts, tenant_id, action)
                """
            )
            _client = client
            _table_ready = True
            logger.info("connected to ClickHouse and ensured audit_events table")
            return client
        except Exception as exc:  # noqa: BLE001 — broad on purpose, degrade gracefully
            logger.warning("ClickHouse unavailable, buffering events: %s", exc)
            return None


def _row(event: AuditEvent) -> list[Any]:
    return [
        event.ts,
        event.tenant_id,
        event.actor,
        event.action,
        event.resource,
        event.decision,
        json.dumps(event.metadata, default=str, sort_keys=True),
    ]


_COLUMN_NAMES = ["ts", "tenant_id", "actor", "action", "resource", "decision", "metadata"]


def _flush_buffer(client: Any) -> int:
    """Drain the in-memory buffer into ClickHouse. Returns rows flushed."""
    s = get_settings()
    rows: list[list[Any]] = []
    with _buffer_lock:
        while _buffer:
            rows.append(_row(_buffer.popleft()))
    if not rows:
        return 0
    try:
        client.insert(f"{s.clickhouse_database}.audit_events", rows, column_names=_COLUMN_NAMES)
        logger.info("flushed %d buffered events", len(rows))
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("buffer flush failed, requeueing %d events: %s", len(rows), exc)
        with _buffer_lock:
            # Requeue at the front, preserving order. deque has no extendleft-in-order, so reverse first.
            for row_event in reversed(rows):
                if len(_buffer) >= _BUFFER_CAP:
                    logger.error("buffer full, dropping oldest event")
                    _buffer.popleft()
                _buffer.appendleft(_event_from_row(row_event))
        return 0


def _event_from_row(row: list[Any]) -> AuditEvent:
    return AuditEvent(
        ts=row[0],
        tenant_id=row[1],
        actor=row[2],
        action=row[3],
        resource=row[4],
        decision=row[5],
        metadata=json.loads(row[6]) if row[6] else {},
    )


# ── Routes ───────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz() -> dict[str, Any]:
    s = get_settings()
    return {
        "status": "ok",
        "service": "audit-service",
        "clickhouse_target": f"{s.clickhouse_host}:{s.clickhouse_port}",
        "clickhouse_connected": _client is not None,
        "buffered_events": len(_buffer),
        "spooled_events": _spool.count() if _spool is not None else 0,
    }


@app.post("/events", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_bearer)])
def ingest_event(event: AuditEvent) -> dict[str, Any]:
    """Accept an audit event. Writes to ClickHouse; falls back to the
    in-memory buffer if ClickHouse is unreachable so callers stay
    non-blocking. Always returns 202 unless validation fails (Pydantic
    handles that automatically with 422)."""
    s = get_settings()
    client = _connect()
    key = f"{event.ts.isoformat()}|{event.tenant_id}|{event.action}|{event.resource}"

    if client is None:
        _buffer_or_spool(event)
        return {"accepted": True, "key": key, "persisted": False, "buffered": True}

    # Drain any buffered events alongside this one.
    _flush_buffer(client)
    try:
        client.insert(
            f"{s.clickhouse_database}.audit_events",
            [_row(event)],
            column_names=_COLUMN_NAMES,
        )
        if _spool is not None:
            for spooled in _spool.drain():
                with _buffer_lock:
                    _buffer.append(spooled)
            _flush_buffer(client)
        return {"accepted": True, "key": key, "persisted": True, "buffered": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("insert failed, buffering: %s", exc)
        _buffer_or_spool(event)
        return {"accepted": True, "key": key, "persisted": False, "buffered": True}


@app.get("/events", dependencies=[Depends(require_bearer)])
def query_events(
    tenant_id: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    since: datetime | None = Query(default=None, description="ISO-8601, inclusive lower bound on ts"),
    until: datetime | None = Query(default=None, description="ISO-8601, exclusive upper bound on ts"),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Query audit events with the given filters. Returns up to `limit`
    rows, most recent first."""
    s = get_settings()
    client = _connect()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit store unavailable",
        )

    filters: list[str] = []
    params: dict[str, Any] = {}
    if tenant_id is not None:
        filters.append("tenant_id = {tenant_id:String}")
        params["tenant_id"] = tenant_id
    if actor is not None:
        filters.append("actor = {actor:String}")
        params["actor"] = actor
    if action is not None:
        filters.append("action = {action:String}")
        params["action"] = action
    if resource is not None:
        filters.append("resource = {resource:String}")
        params["resource"] = resource
    if decision is not None:
        filters.append("decision = {decision:String}")
        params["decision"] = decision
    if since is not None:
        filters.append("ts >= {since:DateTime64(3)}")
        params["since"] = since
    if until is not None:
        filters.append("ts < {until:DateTime64(3)}")
        params["until"] = until

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = (
        f"SELECT ts, tenant_id, actor, action, resource, decision, metadata "
        f"FROM {s.clickhouse_database}.audit_events {where} "
        f"ORDER BY ts DESC LIMIT {limit}"
    )
    try:
        result = client.query(sql, parameters=params)
    except Exception as exc:  # noqa: BLE001
        logger.exception("query failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"query failed: {exc}",
        ) from exc

    events = [
        {
            "ts": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
            "tenant_id": row[1],
            "actor": row[2],
            "action": row[3],
            "resource": row[4],
            "decision": row[5],
            "metadata": json.loads(row[6]) if row[6] else {},
        }
        for row in result.result_rows
    ]
    return {"events": events, "count": len(events)}


# Translate uncaught errors into JSON problem detail (RFC 7807-ish) so
# clients never get an HTML 500 page. Endpoint-specific errors still use
# HTTPException with their proper status codes above.
@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception) -> JSONResponse:  # type: ignore[no-untyped-def]
    logger.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content={
            "type": "about:blank",
            "title": "internal server error",
            "status": 500,
            "detail": str(exc),
        },
    )
