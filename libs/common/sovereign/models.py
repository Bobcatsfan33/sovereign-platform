from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class InstanceStatus(StrEnum):
    provisioning = "provisioning"
    succeeded = "succeeded"
    failed = "failed"
    deprovisioning = "deprovisioning"


class DriftStatus(StrEnum):
    unknown = "unknown"
    in_sync = "in_sync"
    drifted = "drifted"
    reconciling = "reconciling"


class OperationState(StrEnum):
    in_progress = "in progress"
    succeeded = "succeeded"
    failed = "failed"


class Listener(BaseModel):
    name: str
    port: int = Field(ge=1, le=65535)
    protocol: str = "HTTP"

class Route(BaseModel):
    host: str
    prefix: str = "/"
    cluster: str

class Cluster(BaseModel):
    name: str
    endpoints: list[str]

    @field_validator("endpoints")
    @classmethod
    def require_endpoints(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("cluster must have at least one endpoint")
        return v

class LbParameters(BaseModel):
    region: str = "us-east-1"
    listeners: list[Listener] = Field(default_factory=lambda: [Listener(name="http", port=8080)])
    routes: list[Route] = Field(default_factory=list)
    clusters: list[Cluster] = Field(default_factory=list)
    mtls_enabled: bool = False
    sidecar_mode: bool = False
    tags: dict[str, str] = Field(default_factory=dict)

class ServiceInstance(BaseModel):
    # Persisted-payload schema version (see migrations.py). Tracks
    # CURRENT_SCHEMA_VERSIONS["instance"]; bump both together with a migration.
    schema_version: int = 1
    instance_id: str
    service_id: str
    plan_id: str
    organization_guid: str | None = None
    space_guid: str | None = None
    parameters: LbParameters
    status: InstanceStatus = InstanceStatus.provisioning
    version: int = 1
    applied_version: int | None = None
    operation_id: str | None = None
    operation_type: str | None = None
    operation_state: OperationState | None = None
    operation_reason: str = ""
    failed_step_kind: str | None = None
    apply_outputs: dict[str, Any] = Field(default_factory=dict)
    drift_status: DriftStatus = DriftStatus.unknown
    reconcile_attempts: int = 0
    last_reconciled_at: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

class Binding(BaseModel):
    # Persisted-payload schema version (see migrations.py). Tracks
    # CURRENT_SCHEMA_VERSIONS["binding"]; bump both together with a migration.
    schema_version: int = 1
    binding_id: str
    instance_id: str
    app_guid: str | None = None
    credentials: dict[str, str]
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

class ProvisionRequest(BaseModel):
    service_id: str
    plan_id: str
    organization_guid: str | None = None
    space_guid: str | None = None
    parameters: LbParameters = Field(default_factory=LbParameters)

class UpdateRequest(BaseModel):
    service_id: str | None = None
    plan_id: str | None = None
    parameters: LbParameters | None = None

class BindRequest(BaseModel):
    service_id: str | None = None
    plan_id: str | None = None
    app_guid: str | None = None

class RenderRequest(BaseModel):
    instance: ServiceInstance


# ─────────────────────────────────────────────────────────────────────
# Governance models — merged from sovereign-ai-broker during Phase 0.1.
# These are the shared shapes used by the dedicated audit service,
# metering service, and policy engine that the base chassis depends on.
# ─────────────────────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    """A single audit record. Replaces the fabric's prior inline 5-field
    ClickHouse schema with a tenant-aware, decision-aware shape so audit
    output is usable for hierarchical tenancy (Phase 3) and policy
    decision review (Phase 2)."""

    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str = "default"
    actor: str = "system"
    action: str
    resource: str
    decision: str = "allow"
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str | None = None
    event_hash: str | None = None
    signature_key_id: str | None = None
    signature: str | None = None


class PolicyRequest(BaseModel):
    """Input to the policy engine. The engine evaluates the action against
    the configured Rego bundle and returns a PolicyDecision."""

    tenant_id: str
    actor: str
    action: str
    resource: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    """Output of the policy engine. `obligations` are side-effects the
    caller must honor (e.g. PII redaction, logging, human approval).

    Phase 2 fields:
        denies          per-rule reasons that caused the deny. Empty when
                        `allow` is true. Each entry cites a control id
                        (e.g. "SC-8: TLS must be enabled on ...").
        matched_layers  which policy layers contributed denies
                        ("base", "pack:ai-pack", "tenant:agency-x").
    """

    allow: bool
    reason: str = ""
    obligations: list[str] = Field(default_factory=list)
    denies: list[str] = Field(default_factory=list)
    matched_layers: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    """A metering record. Persisted by the dedicated metering service and
    later aggregated for the quota and chargeback system in Phase 3."""

    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str
    resource_id: str
    resource_type: str
    quantity: float = Field(ge=0)
    unit: str
    metadata: dict[str, Any] = Field(default_factory=dict)
