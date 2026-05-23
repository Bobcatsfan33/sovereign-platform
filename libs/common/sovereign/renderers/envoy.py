"""Envoy renderer — the chassis's first concrete `BaseRenderer`.

Wraps the existing Phase-0 logic (`render_envoy` + `validate_bootstrap`)
behind the renderer interface so the broker and control-plane go
through the registry instead of hardcoding the load-balancer path. The
public OSB behaviour (provision/bind/etc.) is unchanged — the refactor
is purely internal.

S3 is the apply target. The renderer holds its own boto3 client so
the control-plane stays a thin HTTP shell; service-pack renderers
follow the same pattern (own their backend client, expose
`render/validate/apply/teardown`).
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import boto3
import yaml
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from ..envoy_v3 import validate_bootstrap
from ..models import ServiceInstance
from ..render import RenderValidationError, _build_doc
from ..settings import get_settings
from .artifact import (
    ApplyResult,
    DeploymentStep,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
)
from .base import BaseRenderer

logger = logging.getLogger("sovereign.renderers.envoy")


def _s3_client() -> Any:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.aws_region,
    )


def _key_for(instance_id: str, version: int, filename: str = "envoy.yaml") -> str:
    return f"instances/{instance_id}/v{version}/{filename}"


class EnvoyRenderer(BaseRenderer):
    service_type: ClassVar[str] = "sovereign-envoy-lb"

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        # Reuse Phase-0 build + validate so behaviour is bit-for-bit
        # identical to the previous render path; the only difference is
        # the artifact wrapper.
        doc = _build_doc(instance)
        try:
            validate_bootstrap(doc)
        except ValidationError as exc:
            raise RenderValidationError(
                f"rendered Envoy config failed schema validation: {exc}"
            ) from exc

        yaml_bytes = yaml.safe_dump(doc, sort_keys=False).encode()
        s = get_settings()
        key = _key_for(instance.instance_id, instance.version)

        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"envoy.yaml": yaml_bytes},
            metadata={
                "listener_count": len(instance.parameters.listeners),
                "cluster_count": len(instance.parameters.clusters),
                "route_count": len(instance.parameters.routes),
            },
            deployment_manifest=[
                DeploymentStep(
                    kind="s3-put",
                    target=key,
                    payload={
                        "bucket": s.config_bucket,
                        "content_type": "application/x-yaml",
                    },
                ),
                DeploymentStep(
                    kind="envoy-snapshot",
                    target=instance.instance_id,
                    payload={"version": instance.version},
                ),
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        """Re-parse the YAML payload and confirm it's still valid Envoy
        v3. Cheap belt-and-braces over render-time validation; catches
        an artifact that was mutated in transit."""
        body = artifact.config_files.get("envoy.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing envoy.yaml in artifact"])
        try:
            doc = yaml.safe_load(body)
            validate_bootstrap(doc)
        except (ValidationError, yaml.YAMLError) as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        applied: list[DeploymentStep] = []
        s = get_settings()
        s3 = _s3_client()
        for step in artifact.deployment_manifest:
            if step.kind == "s3-put":
                filename = step.target.rsplit("/", 1)[-1]
                body = artifact.config_files.get(filename)
                if body is None:
                    return ApplyResult(
                        ok=False,
                        applied_steps=applied,
                        failed_step=step,
                        detail=f"no config_files entry for {filename!r}",
                    )
                try:
                    s3.put_object(
                        Bucket=step.payload.get("bucket", s.config_bucket),
                        Key=step.target,
                        Body=body,
                        ContentType=step.payload.get("content_type", "application/octet-stream"),
                    )
                except (ClientError, BotoCoreError) as exc:
                    return ApplyResult(
                        ok=False,
                        applied_steps=applied,
                        failed_step=step,
                        detail=f"S3 put failed: {exc}",
                    )
                applied.append(step)
            elif step.kind == "envoy-snapshot":
                # Envoy hosts poll the S3 path on a timer; there's no
                # active orchestration to do. The step is logged so the
                # operator can see the snapshot was published.
                logger.info(
                    "envoy-snapshot published for %s v%s",
                    step.target,
                    step.payload.get("version"),
                )
                applied.append(step)
            else:
                logger.warning(
                    "EnvoyRenderer.apply skipping unknown step kind %r", step.kind
                )
        return ApplyResult(ok=True, applied_steps=applied)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        """Delete every S3 object under instances/<id>/. Best-effort —
        the OSB deprovision response is independent of this success."""
        s = get_settings()
        s3 = _s3_client()
        prefix = f"instances/{instance.instance_id}/"
        removed: list[str] = []
        failed: list[str] = []
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=s.config_bucket, Prefix=prefix):
                for obj in page.get("Contents", []) or []:
                    key = obj["Key"]
                    try:
                        s3.delete_object(Bucket=s.config_bucket, Key=key)
                        removed.append(key)
                    except (ClientError, BotoCoreError) as exc:
                        failed.append(f"{key}: {exc}")
        except (ClientError, BotoCoreError) as exc:
            return TeardownResult(ok=False, removed=removed, failed=failed, detail=str(exc))
        return TeardownResult(ok=not failed, removed=removed, failed=failed)
