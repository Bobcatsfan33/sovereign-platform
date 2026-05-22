from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field, field_validator

class InstanceStatus(str, Enum):
    provisioning = "provisioning"
    succeeded = "succeeded"
    failed = "failed"
    deprovisioning = "deprovisioning"

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
    instance_id: str
    service_id: str
    plan_id: str
    organization_guid: str | None = None
    space_guid: str | None = None
    parameters: LbParameters
    status: InstanceStatus = InstanceStatus.provisioning
    version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class Binding(BaseModel):
    binding_id: str
    instance_id: str
    app_guid: str | None = None
    credentials: dict[str, str]
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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
