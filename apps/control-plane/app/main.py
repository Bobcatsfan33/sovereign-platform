"""Sovereign Platform — Envoy control plane.

Renders Envoy v3 configs from instance specs and persists them as
immutable artifacts in S3. Serves the rendered config to Envoy hosts on
demand.

Task 0.5 hardening: JSON problem detail on errors. The /get-config
endpoint now returns raw YAML with the correct content-type rather than
JSON-wrapped YAML. S3 failures translate to 503 with a structured body.
"""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, HTTPException, Response, status
from sovereign.audit import Audit
from sovereign.errors import install_problem_detail_handlers
from sovereign.models import RenderRequest
from sovereign.render import RenderValidationError, render_envoy
from sovereign.security import require_bearer
from sovereign.settings import get_settings

logger = logging.getLogger("control-plane")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Sovereign Platform — Envoy Control Plane", version="0.1.0")
install_problem_detail_handlers(app, service_name="control-plane")

audit = Audit(service="control-plane")


def _s3_client() -> Any:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.aws_region,
    )


@app.on_event("startup")
def startup() -> None:
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
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "control-plane"}


@app.post("/render", dependencies=[Depends(require_bearer)])
def render(req: RenderRequest) -> dict[str, Any]:
    s = get_settings()
    try:
        body = render_envoy(req.instance)
    except RenderValidationError as exc:
        # The rendered doc failed Envoy v3 schema validation. Refuse to
        # write it to S3 — surface the structured error to the caller so
        # they can correct the request (or report the template bug).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    key = f"instances/{req.instance.instance_id}/v{req.instance.version}/envoy.yaml"
    try:
        _s3_client().put_object(
            Bucket=s.config_bucket,
            Key=key,
            Body=body.encode(),
            ContentType="application/x-yaml",
        )
    except (ClientError, BotoCoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"object store unavailable: {exc}",
        ) from exc

    audit.emit(
        "config.rendered",
        req.instance.instance_id,
        details=key,
        metadata={"version": req.instance.version, "bucket": s.config_bucket},
    )
    return {"bucket": s.config_bucket, "key": key, "version": req.instance.version}


@app.get("/instances/{instance_id}/versions/{version}/envoy.yaml")
def get_config(instance_id: str, version: int) -> Response:
    """Return the rendered Envoy YAML for the given instance + version.

    Returns raw YAML with `application/x-yaml` so Envoy hosts can consume
    it directly — previously the str return type caused FastAPI to JSON-
    encode the body, breaking real Envoy clients."""
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
