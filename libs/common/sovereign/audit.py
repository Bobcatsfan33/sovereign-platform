"""Audit emitter — HTTP client to the dedicated audit service.

Until Phase 0 task 0.2, services wrote audit events directly to ClickHouse.
That coupling meant ClickHouse latency or downtime surfaced as broker
failures. This module replaces the inline writer with an HTTP client to
the audit service; the audit service owns the ClickHouse session and
handles buffering. The `Audit.emit(...)` call signature is preserved so
existing call sites in apps/broker and apps/control-plane keep working.

Audit emission is best-effort from the caller's point of view: send
failures are logged at WARNING but never propagate. Durability is the
audit service's responsibility (it buffers when ClickHouse is degraded).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import AuditEvent
from .settings import get_settings

logger = logging.getLogger("sovereign.audit")


class Audit:
    """Synchronous HTTP client used by services to emit audit events.

    A single instance per service is sufficient — the underlying
    `httpx.Client` is thread-safe and pools connections.
    """

    def __init__(self, service: str | None = None, timeout: float = 2.0) -> None:
        s = get_settings()
        self._base_url = s.audit_service_url.rstrip("/")
        self._token = s.dev_bearer_token
        self._service = service or s.service_name
        self._client = httpx.Client(timeout=timeout)

    def emit(
        self,
        action: str,
        resource: str,
        details: str = "",
        actor: str | None = None,
        *,
        tenant_id: str = "default",
        decision: str = "allow",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send a single audit event. Best-effort — never raises on
        transport errors. Keyword-only `tenant_id`, `decision`, and
        `metadata` extend the prior 4-arg signature without breaking it."""
        meta: dict[str, Any] = dict(metadata or {})
        if details:
            meta.setdefault("details", details)
        meta.setdefault("emitted_by", self._service)
        event = AuditEvent(
            tenant_id=tenant_id,
            actor=actor or "system",
            action=action,
            resource=resource,
            decision=decision,
            metadata=meta,
        )
        try:
            response = self._client.post(
                f"{self._base_url}/events",
                json=event.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {self._token}"},
            )
            if response.status_code >= 400:
                logger.warning(
                    "audit service returned %s for action=%s: %s",
                    response.status_code,
                    action,
                    response.text[:200],
                )
        except httpx.HTTPError as exc:
            logger.warning("audit emit failed for action=%s: %s", action, exc)

    def close(self) -> None:
        self._client.close()
