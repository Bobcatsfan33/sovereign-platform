"""Sovereign Platform — Open Service Broker (OSB v2 API).

Phase 1 update: the catalog is now read from the DynamoDB-backed
CatalogStore (task 1.7). On startup, the broker walks the renderer and
connector registries and persists each component's `catalog_entry()`
into the store. Packs added later via the pack registration system
(task 1.9) appear in `/v2/catalog` automatically — the route reads
from DynamoDB, no broker code change needed.

Phase 0 hardening is preserved: RFC 7807 problem detail on every
endpoint, idempotent OSB semantics (410 on deprovision-missing,
already_exists on reprovision), graceful 503 on downstream failure.
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
from sovereign.catalog import CatalogStore
from sovereign.connectors import registry as connector_registry
from sovereign.connectors.github import GitHubConnector  # noqa: F401
from sovereign.connectors.s3 import S3Connector  # noqa: F401
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
from sovereign.renderers import register_renderer
from sovereign.renderers import registry as renderer_registry

# Importing these modules has the side effect of pre-registering the
# chassis renderers + connectors into their registries. Pack discovery
# (task 1.9) adds more entries via a discovery scan at startup.
from sovereign.renderers.envoy import EnvoyRenderer  # noqa: F401  (side-effect import)
from sovereign.settings import get_settings
from sovereign.store import Store

# EnvoyRenderer is registered in the control-plane process. The broker
# also needs it in its own registry for catalog seeding (the broker
# never calls renderer.render itself — that happens in the control
# plane — but it needs the catalog_entry() metadata).
register_renderer(EnvoyRenderer())

logger = logging.getLogger("broker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Sovereign Platform — OSB Broker", version="0.2.0")
install_problem_detail_handlers(app, service_name="broker")

security = HTTPBasic(auto_error=False)
store = Store()
catalog = CatalogStore()
audit = Audit(service="broker")


def auth(creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    s = get_settings()
    if creds is None:
        return
    if not (
        secrets.compare_digest(creds.username, s.broker_username)
        and secrets.compare_digest(creds.password, s.broker_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")


def _seed_catalog() -> None:
    """Walk the renderer + connector registries and upsert each
    component's catalog_entry() into the DynamoDB catalog. Idempotent —
    calling repeatedly is safe and is how packs get re-discovered on
    broker restart."""
    try:
        catalog.ensure_table()
    except Exception:  # noqa: BLE001
        logger.exception("catalog ensure_table failed; will retry on next startup")
        return

    services = 0
    for service_type in renderer_registry.service_types():
        renderer = renderer_registry.get(service_type)
        if renderer is None:
            continue
        entry = type(renderer).catalog_entry()
        if entry is None:
            continue
        try:
            catalog.put_service(entry)
            services += 1
        except Exception:  # noqa: BLE001
            logger.exception("failed to seed service catalog entry for %s", service_type)

    connectors = 0
    for connector_type in connector_registry.connector_types():
        cls = connector_registry.get(connector_type)
        if cls is None:
            continue
        entry = cls.catalog_entry()
        if entry is None:
            continue
        try:
            catalog.put_connector(entry)
            connectors += 1
        except Exception:  # noqa: BLE001
            logger.exception("failed to seed connector catalog entry for %s", connector_type)

    logger.info(
        "catalog seeded: %d service entries, %d connector entries", services, connectors
    )


@app.on_event("startup")
def startup() -> None:
    try:
        store.ensure_tables()
    except Exception:  # noqa: BLE001
        logger.exception("ensure_tables failed at startup; will retry on first request")
    _seed_catalog()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "broker",
        "renderers": renderer_registry.service_types(),
        "connectors": connector_registry.connector_types(),
    }


@app.get("/v2/catalog", dependencies=[Depends(auth)])
def get_catalog() -> dict[str, Any]:
    """Return the persisted service catalog in OSB v2 shape. Two
    extensions over the OSB minimum:
      - `connectors`: the parallel connector catalog so the UI can
        list both in one round-trip.
      - `parameter_schema` and `tags` on each service.
    """
    try:
        services = catalog.list_services()
        connectors = catalog.list_connectors()
    except RuntimeError as exc:
        # Catalog table missing or query failed — degrade to whatever
        # the in-memory registries advertise so an empty DynamoDB
        # doesn't break the OSB clients.
        logger.warning("catalog read failed (%s); falling back to live registries", exc)
        services = [
            e
            for st in renderer_registry.service_types()
            for r in [renderer_registry.get(st)]
            if r is not None
            for e in [type(r).catalog_entry()]
            if e is not None
        ]
        connectors = [
            e
            for ct in connector_registry.connector_types()
            for cls in [connector_registry.get(ct)]
            if cls is not None
            for e in [cls.catalog_entry()]
            if e is not None
        ]

    return {
        "services": [
            {
                "id": e.service_type,
                "name": e.name,
                "description": e.description,
                "bindable": e.bindable,
                "tags": e.tags,
                "metadata": {**e.metadata, "pack": e.pack},
                "plans": [p.model_dump() for p in e.plans],
                "parameter_schema": e.parameter_schema.model_dump(by_alias=True),
            }
            for e in services
        ],
        "connectors": [
            {
                "id": e.connector_type,
                "name": e.name,
                "description": e.description,
                "metadata": {**e.metadata, "pack": e.pack},
                "capabilities": e.capabilities,
                "config_schema": e.config_schema.model_dump(by_alias=True),
            }
            for e in connectors
        ],
    }


async def render(instance: ServiceInstance) -> dict[str, Any]:
    """Ask the control plane to render this instance's config artifact."""
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

    artifact = await render(inst)
    inst.status = InstanceStatus.succeeded
    try:
        store.put_instance(inst)
    except ClientError as exc:
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
