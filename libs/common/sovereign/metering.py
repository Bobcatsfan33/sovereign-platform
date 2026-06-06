"""Metering emitter — HTTP client to the dedicated metering service.

Mirrors the Audit client (Phase 0): in-process services call
`Metering.record(...)` and the call becomes a fire-and-forget POST to
the metering service which persists to DynamoDB. Best-effort —
transport failures log at WARNING but never propagate.

The broker uses this to attribute provisioning events to the
(tenant_id, service_type, pack) tuple so the QuotaEnforcer (Phase 3
task 3.4) can compute current usage and gate future provisions.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import Usage
from .security import service_auth_headers
from .settings import get_settings

logger = logging.getLogger("sovereign.metering")


class Metering:
    """Synchronous HTTP client for the dedicated metering service."""

    def __init__(self, service: str | None = None, timeout: float = 2.0) -> None:
        s = get_settings()
        self._base_url = s.metering_service_url.rstrip("/")
        self._service = service or s.service_name
        self._client = httpx.Client(timeout=timeout)

    def record(
        self,
        *,
        tenant_id: str,
        resource_id: str,
        resource_type: str,
        quantity: float = 1.0,
        unit: str = "instance",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send a single Usage record. Best-effort: HTTPError is logged
        and swallowed so a metering outage cannot block provision."""
        meta = dict(metadata or {})
        meta.setdefault("emitted_by", self._service)
        usage = Usage(
            tenant_id=tenant_id,
            resource_id=resource_id,
            resource_type=resource_type,
            quantity=quantity,
            unit=unit,
            metadata=meta,
        )
        try:
            response = self._client.post(
                f"{self._base_url}/usage",
                json=usage.model_dump(mode="json"),
                headers=service_auth_headers(),
            )
            if response.status_code >= 400:
                logger.warning(
                    "metering service returned %s: %s",
                    response.status_code,
                    response.text[:200],
                )
        except httpx.HTTPError as exc:
            logger.warning("metering record failed: %s", exc)

    def close(self) -> None:
        self._client.close()
