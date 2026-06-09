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

import hashlib
import json
import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sovereign.audit_signing import sign_audit_event
from sovereign.audit_spool import AuditSpool
from sovereign.cors import install_cors
from sovereign.models import AuditEvent
from sovereign.observability import install_metrics_endpoint
from sovereign.ratelimit import install_rate_limit
from sovereign.security import require_bearer
from sovereign.settings import get_settings
from sovereign.version import __version__

logger = logging.getLogger("audit-service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Sovereign Platform — Audit Service", version=__version__)
install_cors(app)
install_rate_limit(app)

# ── ClickHouse client (lazy, with graceful degradation) ───────────────

_BUFFER_CAP = 1000
_buffer: deque[AuditEvent] = deque(maxlen=_BUFFER_CAP)
_buffer_lock = threading.Lock()
_client_lock = threading.Lock()
_chain_lock = threading.Lock()
_client: Any = None  # clickhouse_connect.driver.Client | None — typed loosely to avoid hard import at module load
_table_ready = False
_last_event_hash: str | None = None

_spool: AuditSpool | None = (
    AuditSpool(get_settings().audit_spool_path) if get_settings().audit_spool_path else None
)


def _metrics_gauges() -> dict[str, int]:
    return {
        "audit_buffered_events": len(_buffer),
        "audit_spooled_events": _spool.count() if _spool is not None else 0,
        "audit_clickhouse_connected": 1 if _client is not None else 0,
    }


install_metrics_endpoint(app, service="audit-service", extra_gauges=_metrics_gauges)


def _canonical_event_payload(event: AuditEvent) -> str:
    return json.dumps(
        event.model_dump(mode="json", exclude={"event_hash", "signature_key_id", "signature"}),
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )


def _chain_event(event: AuditEvent) -> AuditEvent:
    """Attach previous_hash/event_hash to an accepted audit event."""
    global _last_event_hash
    with _chain_lock:
        chained = event.model_copy(update={"previous_hash": _last_event_hash, "event_hash": None})
        event_hash = hashlib.sha256(_canonical_event_payload(chained).encode("utf-8")).hexdigest()
        chained = chained.model_copy(update={"event_hash": event_hash})
        _last_event_hash = event_hash
        return chained


def _ensure_chained(event: AuditEvent) -> AuditEvent:
    if event.event_hash:
        return event
    return _chain_event(event)


def _prepare_event(event: AuditEvent) -> AuditEvent:
    return sign_audit_event(_ensure_chained(event))


def _export_to_siem(event: AuditEvent) -> None:
    s = get_settings()
    if not s.siem_webhook_url:
        return
    headers: dict[str, str] = {}
    if s.siem_webhook_token:
        headers["Authorization"] = f"Bearer {s.siem_webhook_token}"
    try:
        with httpx.Client(timeout=s.siem_webhook_timeout_seconds) as client:
            response = client.post(
                s.siem_webhook_url,
                json=event.model_dump(mode="json"),
                headers=headers,
            )
            if response.status_code >= 400:
                logger.warning("SIEM webhook returned %s", response.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SIEM webhook export failed: %s", exc)


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
            ttl_clause = _ttl_clause(s.audit_retention_days)
            client.command(
                f"""
                CREATE TABLE IF NOT EXISTS {s.clickhouse_database}.audit_events (
                  ts DateTime64(3),
                  tenant_id String,
                  actor String,
                  action String,
                  resource String,
                  decision String,
                  metadata String,
                  previous_hash Nullable(String),
                  event_hash String,
                  signature_key_id Nullable(String),
                  signature Nullable(String)
                ) ENGINE = MergeTree
                ORDER BY (ts, tenant_id, action)
                {ttl_clause}
                """
            )
            client.command(
                f"ALTER TABLE {s.clickhouse_database}.audit_events "
                "ADD COLUMN IF NOT EXISTS previous_hash Nullable(String)"
            )
            client.command(
                f"ALTER TABLE {s.clickhouse_database}.audit_events "
                "ADD COLUMN IF NOT EXISTS event_hash String DEFAULT ''"
            )
            client.command(
                f"ALTER TABLE {s.clickhouse_database}.audit_events "
                "ADD COLUMN IF NOT EXISTS signature_key_id Nullable(String)"
            )
            client.command(
                f"ALTER TABLE {s.clickhouse_database}.audit_events "
                "ADD COLUMN IF NOT EXISTS signature Nullable(String)"
            )
            if ttl_clause:
                client.command(
                    f"ALTER TABLE {s.clickhouse_database}.audit_events MODIFY {ttl_clause}"
                )
            _client = client
            _table_ready = True
            logger.info("connected to ClickHouse and ensured audit_events table")
            return client
        except Exception as exc:  # noqa: BLE001 — broad on purpose, degrade gracefully
            logger.warning("ClickHouse unavailable, buffering events: %s", exc)
            return None


def _ttl_clause(days: int) -> str:
    if days <= 0:
        return ""
    return f"TTL ts + INTERVAL {days} DAY DELETE"


def _row(event: AuditEvent) -> list[Any]:
    return [
        event.ts,
        event.tenant_id,
        event.actor,
        event.action,
        event.resource,
        event.decision,
        json.dumps(event.metadata, default=str, sort_keys=True),
        event.previous_hash,
        event.event_hash or "",
        event.signature_key_id,
        event.signature,
    ]


_COLUMN_NAMES = [
    "ts",
    "tenant_id",
    "actor",
    "action",
    "resource",
    "decision",
    "metadata",
    "previous_hash",
    "event_hash",
    "signature_key_id",
    "signature",
]


def _flush_buffer(client: Any) -> int:
    """Drain the in-memory buffer into ClickHouse. Returns rows flushed."""
    s = get_settings()
    rows: list[list[Any]] = []
    with _buffer_lock:
        while _buffer:
            rows.append(_row(_prepare_event(_buffer.popleft())))
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
        previous_hash=row[7] if len(row) > 7 else None,
        event_hash=row[8] if len(row) > 8 else None,
        signature_key_id=row[9] if len(row) > 9 else None,
        signature=row[10] if len(row) > 10 else None,
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
    event = _prepare_event(event)
    client = _connect()
    key = f"{event.ts.isoformat()}|{event.tenant_id}|{event.action}|{event.resource}"

    if client is None:
        _buffer_or_spool(event)
        _export_to_siem(event)
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
        _export_to_siem(event)
        return {"accepted": True, "key": key, "persisted": True, "buffered": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("insert failed, buffering: %s", exc)
        _buffer_or_spool(event)
        _export_to_siem(event)
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
        f"SELECT ts, tenant_id, actor, action, resource, decision, metadata, "
        f"previous_hash, event_hash, signature_key_id, signature "
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
            "previous_hash": row[7] if len(row) > 7 else None,
            "event_hash": row[8] if len(row) > 8 else None,
            "signature_key_id": row[9] if len(row) > 9 else None,
            "signature": row[10] if len(row) > 10 else None,
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
