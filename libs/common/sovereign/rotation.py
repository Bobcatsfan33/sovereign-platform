"""Secret-rotation webhook (WS5).

Completes the rotation story: TTL auto-refetch (RotatingSecretsProvider) picks
up a rotation within one interval, but a secrets manager that emits a rotation
event can trigger an *instant* cutover by POSTing this endpoint. Each service
process holds its own cached settings + provider, so the rotation system fans
the webhook out to every instance; each one expires its cache and re-resolves.

The endpoint is authenticated with the same `require_bearer` dependency as the
rest of the platform (mTLS/workload-identity or bearer) and never returns
secret values — only which provider refreshed.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from .security import require_bearer


def install_rotation_webhook(app: FastAPI) -> None:
    async def refresh_secrets(_identity: str = Depends(require_bearer)) -> dict[str, Any]:
        from .settings import refresh_managed_secrets

        settings = refresh_managed_secrets()
        return {"refreshed": True, "provider": settings.secrets_provider}

    app.add_api_route(
        "/admin/secrets/refresh",
        refresh_secrets,
        methods=["POST"],
        include_in_schema=False,
    )
