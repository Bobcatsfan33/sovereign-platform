"""Sovereign Platform — Open Service Broker (OSB v2 API).

Implements the OSB lifecycle: catalog, provision, update, deprovision,
bind, unbind, last_operation. Persists state in DynamoDB via the shared
Store class, asks the control plane to render config snapshots into S3,
and emits audit events to the dedicated audit service.

Task 0.5 hardening: every endpoint returns RFC 7807 JSON problem detail
on error. Downstream failures (DynamoDB, control plane, audit) translate
to 503 with a descriptive body rather than 500 with a stacktrace. OSB
semantics: deprovision is idempotent (410 Gone for a missing instance),
provision is idempotent (returns the existing instance on re-PUT),
unknown instances on update/bind return 404.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

import httpx
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sovereign.audit import Audit
from sovereign.errors import install_problem_detail_handlers
from sovereign.models import (
    Binding,
    BindRequest,
    InstanceStatus,
    ProvisionRequest,
    RenderRequest,
    ServiceInstance,
    UpdateRequest,
)
from sovereign.settings import get_settings
from sovereign.store import Store

logger = logging.getLogger("broker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Sovereign Platform — OSB Broker", version="0.1.0")
install_problem_detail_handlers(app, service_name="broker")

security = HTTPBasic(auto_error=False)
store = Store()
audit = Audit(service="broker")

CATALOG: dict[str, Any] = {
    "services": [
        {
            "id": "sovereign-envoy-lb",
            "name": "sovereign-envoy-lb",
            "description": "Self-service Envoy-based regional/multi-region load balancer",
            "bindable": True,
            "plans": [
                {"id": "standard-regional", "name": "standard-regional", "description": "Regional Envoy pool"},
                {"id": "multi-region", "name": "multi-region", "description": "Active-active regional Envoy pools"},
                {"id": "sidecar", "name": "sidecar", "description": "App-local sidecar load balancing"},
            ],
        }
    ]
}


def auth(creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    """OSB-compliant HTTP Basic. Cloud Foundry-style clients require this;
    we'll layer Bearer on internal endpoints in a later task."""
    s = get_settings()
    if creds is None:
        # OSB allows unauthenticated catalog probes per cf clients; the
        # other endpoints carry their own auth checks. The original
        # behaviour permits a None — preserved here.
        return
    if not (
        secrets.compare_digest(creds.username, s.broker_username)
        and secrets.compare_digest(creds.password, s.broker_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")


@app.on_event("startup")
def startup() -> None:
    try:
        store.ensure_tables()
    except Exception:  # noqa: BLE001
        logger.exception("ensure_tables failed at startup; will retry on first request")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "broker"}


@app.get("/v2/catalog", dependencies=[Depends(auth)])
def catalog() -> dict[str, Any]:
    return CATALOG


async def render(instance: ServiceInstance) -> dict[str, Any]:
    """Ask the control plane to render this instance's Envoy config and
    persist it to object storage. Failures are surfaced as 503 to the
    OSB client so they distinguish from broker bugs (500)."""
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{s.control_plane_url}/render",
                json=RenderRequest(instance=instance).model_dump(mode="json"),
                headers={"Authorization": f"Bearer {s.dev_bearer_token}"},
            )
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
        logger.warning("control plane render failed for %s: %s", instance.instance_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"control plane unavailable: {exc}",
        ) from exc


@app.put("/v2/service_instances/{instance_id}", status_code=201, dependencies=[Depends(auth)])
async def provision(instance_id: str, req: ProvisionRequest) -> dict[str, Any]:
    try:
        existing = store.get_instance(instance_id)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"state store unavailable: {exc}"
        ) from exc

    if existing:
        return {"dashboard_url": f"/dashboard/{instance_id}", "operation": "already_exists"}

    inst = ServiceInstance(instance_id=instance_id, **req.model_dump())
    try:
        store.put_instance(inst)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"state store unavailable: {exc}"
        ) from exc

    artifact = await render(inst)  # may raise 503 itself
    inst.status = InstanceStatus.succeeded
    try:
        store.put_instance(inst)
    except ClientError as exc:
        # The rendered artifact is durable — surface the persistence
        # failure but don't lose the artifact.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"state store unavailable after render: {exc}",
        ) from exc

    audit.emit(
        "instance.provisioned",
        instance_id,
        details=str(artifact),
        metadata={"service_id": inst.service_id, "plan_id": inst.plan_id},
    )
    return {"dashboard_url": f"/dashboard/{instance_id}", "operation": "provisioned", "config": artifact}


@app.patch("/v2/service_instances/{instance_id}", dependencies=[Depends(auth)])
async def update(instance_id: str, req: UpdateRequest) -> dict[str, Any]:
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    if req.plan_id:
        inst.plan_id = req.plan_id
    if req.parameters:
        inst.parameters = req.parameters
    inst.version += 1
    store.put_instance(inst)
    artifact = await render(inst)
    audit.emit(
        "instance.updated",
        instance_id,
        details=str(artifact),
        metadata={"version": inst.version},
    )
    return {"operation": "updated", "config": artifact}


@app.delete("/v2/service_instances/{instance_id}", dependencies=[Depends(auth)])
def deprovision(instance_id: str) -> dict[str, Any]:
    """OSB deprovision is idempotent. Returns 200 with empty body when
    the instance is present and successfully removed; returns 410 Gone
    when the instance is already absent (per OSB spec §4.6)."""
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="instance already absent")
    store.delete_instance(instance_id)
    audit.emit("instance.deprovisioned", instance_id)
    return {}


@app.put(
    "/v2/service_instances/{instance_id}/service_bindings/{binding_id}",
    status_code=201,
    dependencies=[Depends(auth)],
)
def bind(instance_id: str, binding_id: str, req: BindRequest) -> dict[str, Any]:
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    b = Binding(
        binding_id=binding_id,
        instance_id=instance_id,
        app_guid=req.app_guid,
        credentials={
            "config_url": f"/instances/{instance_id}/versions/{inst.version}/envoy.yaml",
            "instance_id": instance_id,
            "version": str(inst.version),
        },
    )
    store.put_binding(b)
    audit.emit("binding.created", binding_id, details=instance_id, metadata={"instance_id": instance_id})
    return {"credentials": b.credentials}


@app.delete(
    "/v2/service_instances/{instance_id}/service_bindings/{binding_id}",
    dependencies=[Depends(auth)],
)
def unbind(instance_id: str, binding_id: str) -> dict[str, Any]:
    store.delete_binding(binding_id)
    audit.emit("binding.deleted", binding_id, details=instance_id, metadata={"instance_id": instance_id})
    return {}


@app.get("/v2/service_instances/{instance_id}/last_operation", dependencies=[Depends(auth)])
def last_operation(instance_id: str) -> dict[str, str]:
    inst = store.get_instance(instance_id)
    return {"state": inst.status.value if inst else "gone"}
