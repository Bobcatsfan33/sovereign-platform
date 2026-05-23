"""Pydantic models for service catalog entries.

The shape mirrors OSB v2 §2 (service objects, plan objects) so the
broker's `/v2/catalog` response is a 1:1 serialisation of these models.
Two extensions over the OSB minimum:

  - parameter_schema: JSON Schema describing the per-instance request
    parameters. The broker validates against this schema before
    persisting state, and the UI uses it to render the provisioning
    wizard automatically.
  - connectors: a parallel registry of connector entries (S3, GitHub,
    SharePoint, ...) — not in the OSB spec but surfaced through the
    same catalog endpoint so the UI can list them in one place.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParameterSchema(BaseModel):
    """Wrapper around a JSON Schema document. We keep the schema as a
    raw dict (not a typed model) because JSON Schema is itself a generic
    schema language and a pack may declare arbitrary nested constraints.

    `schema_dialect` records which JSON Schema dialect the document uses
    so consumers (UI form renderer, policy engine) can pick the right
    parser. Defaults to draft 2020-12, the current default."""

    schema_dialect: str = "https://json-schema.org/draft/2020-12/schema"
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")

    model_config = {"populate_by_name": True}


class ServicePlan(BaseModel):
    """A t-shirt size for a service type. The chassis ships with three
    plan ids for the load balancer (standard-regional, multi-region,
    sidecar); packs add their own. `metadata` carries free-form display
    hints (price, capacity, region availability) that the UI surfaces."""

    id: str
    name: str
    description: str
    free: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceCatalogEntry(BaseModel):
    """One service type and its plans. Persisted to DynamoDB under
    (kind='service', type_id=service_type)."""

    service_type: str
    name: str
    description: str
    bindable: bool = True
    tags: list[str] = Field(default_factory=list)
    plans: list[ServicePlan] = Field(default_factory=list)
    parameter_schema: ParameterSchema = Field(default_factory=ParameterSchema)
    pack: str = "chassis"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorCatalogEntry(BaseModel):
    """One connector type and its configuration schema. Persisted under
    (kind='connector', type_id=connector_type)."""

    connector_type: str
    name: str
    description: str
    pack: str = "chassis"
    config_schema: ParameterSchema = Field(default_factory=ParameterSchema)
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
