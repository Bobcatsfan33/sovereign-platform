"""Dedicated metering service.

Phase 0 task 0.3 of the Sovereign Platform roadmap. Extracted from
`sovereign-ai-broker/apps/metering/` and re-pointed at a DynamoDB-backed
store (mirroring the fabric's existing state layer). The previous broker
prototype used an in-memory dict which lost every record on restart;
this service persists records to DynamoDB so they survive process
recycles and become the data layer for the Phase 3 quota and chargeback
system.

Endpoints
---------
GET  /healthz   — liveness, unauthenticated.
POST /usage     — record a Usage event. Bearer auth.
GET  /usage     — query usage. Bearer auth. Required: tenant_id.
                   Optional: since, until, resource_id, resource_type, limit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sovereign.apiversion import install_api_versioning
from sovereign.models import Usage
from sovereign.observability import install_metrics_endpoint
from sovereign.ratelimit import install_rate_limit
from sovereign.rotation import install_rotation_webhook
from sovereign.security import require_bearer
from sovereign.usage_store import UsageStore
from sovereign.version import __version__

logger = logging.getLogger("metering-service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Sovereign Platform — Metering Service", version=__version__)
install_api_versioning(app)
install_rotation_webhook(app)
install_rate_limit(app)
install_metrics_endpoint(
    app,
    service="metering-service",
    extra_gauges=lambda: {"metering_table_ensured": 1 if _table_ensured else 0},
)

_store: UsageStore | None = None
_table_ensured: bool = False


def _get_store() -> UsageStore:
    """Return a lazily-initialised UsageStore. The DynamoDB table is
    `ensure_table()`-d the first time the store is requested so the
    service works regardless of whether FastAPI's startup event fires
    (it doesn't in TestClient without an explicit lifespan context)."""
    global _store, _table_ensured
    if _store is None:
        _store = UsageStore()
    if not _table_ensured:
        try:
            _store.ensure_table()
            _table_ensured = True
            logger.info("metering store ready")
        except Exception:  # noqa: BLE001
            logger.exception("ensure_table failed; will retry on next request")
    return _store


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "metering-service"}


@app.post("/usage", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_bearer)])
def record_usage(usage: Usage) -> dict[str, Any]:
    try:
        event_id = _get_store().record(usage)
    except Exception as exc:  # noqa: BLE001
        logger.exception("usage record failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"usage store unavailable: {exc}",
        ) from exc
    return {"accepted": True, "event_id": event_id, "tenant_id": usage.tenant_id}


@app.get("/usage", dependencies=[Depends(require_bearer)])
def query_usage(
    tenant_id: str = Query(..., description="Required — the tenant whose usage to return"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        records = _get_store().query(
            tenant_id,
            since=since,
            until=until,
            resource_id=resource_id,
            resource_type=resource_type,
            limit=limit,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return {
        "tenant_id": tenant_id,
        "count": len(records),
        "usage": [r.model_dump(mode="json") for r in records],
    }


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
