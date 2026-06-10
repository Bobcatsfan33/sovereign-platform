"""Sovereign Platform — Envoy control plane.

Phase 1 refactor: the /render endpoint now dispatches through the
renderer registry rather than calling Envoy code directly. The control
plane is a thin HTTP shell that knows how to do registry lookup, call
render -> validate -> apply, and surface the result. Adding a new
service type means registering a new BaseRenderer — no edits here.

Phase 0 hardening (RFC 7807 problem detail, bearer auth on /render,
raw-YAML response on get_config, graceful 503 on S3 failure) is
preserved.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, HTTPException, Response, status
from sovereign.apiversion import install_api_versioning
from sovereign.audit import Audit
from sovereign.errors import install_problem_detail_handlers
from sovereign.executors import register_default_executors
from sovereign.executors import registry as executor_registry
from sovereign.models import RenderRequest
from sovereign.observability import install_metrics_endpoint
from sovereign.packs import discover_packs, registered_packs
from sovereign.packs.policy_bundles import collect_policy_bundle_dirs
from sovereign.ratelimit import install_rate_limit
from sovereign.render import RenderValidationError
from sovereign.renderers import register_renderer, registry
from sovereign.renderers.envoy import EnvoyRenderer
from sovereign.security import require_bearer
from sovereign.settings import get_settings
from sovereign.version import __version__

logger = logging.getLogger("control-plane")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _startup()
    yield


app = FastAPI(title="Sovereign Platform — Envoy Control Plane", version=__version__, lifespan=lifespan)
install_api_versioning(app)
install_rate_limit(app)
install_problem_detail_handlers(app, service_name="control-plane")
install_metrics_endpoint(
    app,
    service="control-plane",
    extra_gauges=lambda: {
        "control_plane_renderers_registered": len(registry.service_types()),
        "control_plane_executors_registered": len(executor_registry.kinds()),
        "control_plane_packs_registered": len(registered_packs()),
    },
)

audit = Audit(service="control-plane")

# Register the chassis-shipped renderers. Service packs do the same on
# their own import; see Phase 1 task 1.9 (pack registration system).
register_renderer(EnvoyRenderer())


def _s3_client() -> Any:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.aws_region,
    )


def _startup() -> None:
    register_default_executors()
    # Discover packs first so the control plane can dispatch to pack
    # renderers, not just the chassis Envoy renderer.
    discover_packs()
    s = get_settings()
    try:
        client = _s3_client()
        try:
            client.head_bucket(Bucket=s.config_bucket)
        except ClientError:
            client.create_bucket(Bucket=s.config_bucket)
    except (ClientError, BotoCoreError):
        logger.exception("S3 unavailable at startup; will retry on first request")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "control-plane",
        "renderers": registry.service_types(),
        "executors": executor_registry.kinds(),
        "packs": registered_packs(),
        "policy_bundles": collect_policy_bundle_dirs(),
    }


@app.post("/render", dependencies=[Depends(require_bearer)])
async def render(req: RenderRequest) -> dict[str, Any]:
    """Look up the renderer by `instance.service_id`, run render →
    validate → apply, and surface the result. Backward-compatible
    response shape `{bucket, key, version}` for the broker."""
    instance = req.instance
    try:
        renderer = registry.require(instance.service_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no renderer for service_type {instance.service_id!r}",
        ) from exc

    try:
        artifact = await renderer.render(instance)
    except RenderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    vr = await renderer.validate(artifact)
    if not vr.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"artifact validation failed: {vr.errors}",
        )

    ar = await renderer.apply(artifact)
    if not ar.ok:
        failed_step = ar.failed_step.kind if ar.failed_step else ""
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "apply failed",
                "failed_step": failed_step,
                "detail": ar.detail,
            },
        )

    # Backward-compat response — broker has been asserting on this shape
    # since the Phase 0 lifecycle tests. The s3-put step's target IS the
    # key the broker stores in binding credentials.
    s = get_settings()
    s3_step = next((step for step in ar.applied_steps if step.kind == "s3-put"), None)
    key = s3_step.target if s3_step else f"instances/{instance.instance_id}/v{instance.version}/envoy.yaml"

    audit.emit(
        "config.rendered",
        instance.instance_id,
        details=key,
        metadata={
            "service_type": artifact.service_type,
            "version": artifact.version,
            "bucket": s.config_bucket,
            **artifact.metadata,
        },
    )

    return {
        "bucket": s.config_bucket,
        "key": key,
        "version": artifact.version,
        "service_type": artifact.service_type,
        "manifest": [step.model_dump() for step in ar.applied_steps],
    }


@app.post("/diff", dependencies=[Depends(require_bearer)])
async def diff(req: RenderRequest) -> dict[str, Any]:
    """Read-only drift check (ADR-0004). Renders the desired artifact for
    the instance and compares it against live backend state via the
    renderer's diff() (which walks the deployment manifest through the
    executor registry). Never mutates anything. Returns whether the
    instance has drifted; `unknown` means at least one step's backend could
    not be checked, so the caller should NOT treat it as drift (fail-safe)."""
    instance = req.instance
    try:
        renderer = registry.require(instance.service_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no renderer for service_type {instance.service_id!r}",
        ) from exc

    try:
        artifact = await renderer.render(instance)
    except RenderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    md = await renderer.diff(artifact)
    audit.emit(
        "config.diffed",
        instance.instance_id,
        details=("drifted" if md.drifted else "unknown" if md.unknown else "in_sync"),
        metadata={
            "service_type": artifact.service_type,
            "version": artifact.version,
            "drifted": md.drifted,
            "unknown": md.unknown,
        },
    )
    return {
        "instance_id": instance.instance_id,
        "service_type": artifact.service_type,
        "version": artifact.version,
        "drifted": md.drifted,
        "unknown": md.unknown,
        "details": md.details,
    }


@app.get("/instances/{instance_id}/versions/{version}/envoy.yaml")
def get_config(instance_id: str, version: int) -> Response:
    """Return the rendered Envoy YAML for the given instance + version.
    Renderer-agnostic file serving comes later in Phase 1; this route
    stays Envoy-specific for backward compatibility with the existing
    binding `config_url`."""
    s = get_settings()
    key = f"instances/{instance_id}/v{version}/envoy.yaml"
    try:
        obj = _s3_client().get_object(Bucket=s.config_bucket, Key=key)
        body = obj["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no config at {key}",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"object store unavailable: {exc}",
        ) from exc
    except BotoCoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"object store unavailable: {exc}",
        ) from exc

    return Response(content=body, media_type="application/x-yaml")
