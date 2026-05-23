"""Shared data types produced and consumed by the renderer subsystem.

The fabric used to return an ad-hoc dict from the control-plane's /render
endpoint. Phase 1 standardises the shape so the state layer can store any
renderer's output without knowing its service type. The same model is
used by all renderers regardless of pack — Envoy, inference endpoint,
SIEM workspace, vector DB, etc.

Field semantics:

    config_files
        filename -> raw bytes. Persisted to S3 under
        `instances/{instance_id}/v{version}/{filename}`. The Envoy
        renderer produces a single `envoy.yaml`; a future renderer
        (e.g. inference endpoint) may produce multiple files
        (Dockerfile + values.yaml + service-account.yaml).

    metadata
        Free-form, service-type-specific. Persisted to DynamoDB
        alongside the ServiceInstance state. Examples:
        - Envoy: {"listener_count": 1, "cluster_count": 1}
        - inference: {"model_id": "llama-3-8b", "gpu_type": "a100"}
        Keep this small — large blobs belong in config_files.

    deployment_manifest
        Ordered list of `DeploymentStep` actions describing what the
        platform must do to apply this artifact (push to S3, kick a
        K8s rollout, tell Envoy hosts to pull, run a terraform plan).
        Empty list is valid (Envoy hosts poll, no orchestration needed).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class DeploymentStep(BaseModel):
    """One action the platform takes to apply a RenderedArtifact.

    `kind` is a free-form string but conventionally one of:
        s3-put             upload `payload['key']` (bytes already in config_files)
        envoy-snapshot     publish snapshot for Envoy hosts to pull
        k8s-apply          kubectl apply -f payload['manifest']
        helm-upgrade       helm upgrade --install
        terraform-apply    terraform apply in payload['module']
        webhook            POST to payload['url']
    The chassis only knows about s3-put + envoy-snapshot. Service packs
    add new kinds as they need them; the chassis ignores kinds it does
    not understand (logs a warning so unknown manifests are visible).
    """

    kind: str
    target: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class RenderedArtifact(BaseModel):
    """Service-type-agnostic bundle produced by `BaseRenderer.render()`."""

    instance_id: str
    service_type: str
    version: int = Field(ge=1)
    config_files: dict[str, bytes]
    metadata: dict[str, Any] = Field(default_factory=dict)
    deployment_manifest: list[DeploymentStep] = Field(default_factory=list)
    rendered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"arbitrary_types_allowed": True}


class ValidationResult(BaseModel):
    """Returned by `BaseRenderer.validate()`. `ok=False` plus a list of
    error messages indicates the artifact must not be applied."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApplyResult(BaseModel):
    """Returned by `BaseRenderer.apply()`. `applied_steps` is the subset
    of the manifest that ran successfully; `failed_step` (if any) is the
    one that aborted the apply."""

    ok: bool
    applied_steps: list[DeploymentStep] = Field(default_factory=list)
    failed_step: DeploymentStep | None = None
    detail: str = ""


class TeardownResult(BaseModel):
    """Returned by `BaseRenderer.teardown()`. Best-effort: a failure here
    is logged but does not prevent deprovision from completing."""

    ok: bool
    removed: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    detail: str = ""
