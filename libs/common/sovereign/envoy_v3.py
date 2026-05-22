"""Pydantic models for the Envoy v3 bootstrap config subset we generate.

Phase 0 task 0.6 of the Sovereign Platform roadmap. The full Envoy v3
protobuf schema is enormous; this module models only the shape that the
fabric's renderer emits. The intent is to catch template bugs before
they hit S3 — a missing `port_value`, a misspelled `@type`, an empty
`virtual_hosts` list. It is not a complete Envoy validator.

The models use `extra="allow"` so unknown fields (added by future
renderers or service packs in Phase 1) are accepted; required fields
and the field *types* we depend on are enforced strictly.

To validate a rendered config dict, call:

    EnvoyBootstrap.model_validate(doc)

That raises pydantic.ValidationError on any structural problem with a
detailed error path.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _EnvoyModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class SocketAddress(_EnvoyModel):
    address: str
    port_value: int = Field(ge=1, le=65535)
    protocol: Literal["TCP", "UDP"] | None = None


class Address(_EnvoyModel):
    socket_address: SocketAddress


class EndpointHost(_EnvoyModel):
    address: Address


class LbEndpoint(_EnvoyModel):
    endpoint: EndpointHost


class ClusterEndpoints(_EnvoyModel):
    lb_endpoints: list[LbEndpoint] = Field(min_length=1)


class LoadAssignment(_EnvoyModel):
    cluster_name: str
    endpoints: list[ClusterEndpoints] = Field(min_length=1)


class ClusterConfig(_EnvoyModel):
    name: str
    connect_timeout: str = "2s"
    type: str
    load_assignment: LoadAssignment


class RouteMatch(_EnvoyModel):
    prefix: str | None = None
    path: str | None = None


class RouteAction(_EnvoyModel):
    cluster: str


class DirectResponse(_EnvoyModel):
    status: int = Field(ge=100, le=599)


class RouteRule(_EnvoyModel):
    match: RouteMatch
    route: RouteAction | None = None
    direct_response: DirectResponse | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> "RouteRule":
        # `route` and `direct_response` are mutually exclusive — exactly one
        # must be set per Envoy v3 RouteRule.
        if self.route is None and self.direct_response is None:
            raise ValueError("route rule needs either 'route' or 'direct_response'")
        if self.route is not None and self.direct_response is not None:
            raise ValueError("route rule cannot have both 'route' and 'direct_response'")
        return self


class VirtualHost(_EnvoyModel):
    name: str
    domains: list[str] = Field(min_length=1)
    routes: list[RouteRule] = Field(min_length=1)


class RouteConfig(_EnvoyModel):
    name: str
    virtual_hosts: list[VirtualHost] = Field(min_length=1)


class TypedConfig(_EnvoyModel):
    """Envoy's typed_config carries a `@type` URL and message-specific
    fields. Aliased because `@type` is not a valid Python identifier."""
    type_: str = Field(alias="@type")
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class HttpFilter(_EnvoyModel):
    name: str
    typed_config: TypedConfig | None = None


class HttpConnectionManager(TypedConfig):
    stat_prefix: str
    route_config: RouteConfig
    http_filters: list[HttpFilter] = Field(min_length=1)


# URL fragment that identifies the HttpConnectionManager typed_config.
# Discriminated on substring match because Envoy occasionally bumps the
# fully-qualified path (v2 → v3) but the message name is stable.
_HCM_TYPE_FRAGMENT = "HttpConnectionManager"


class NetworkFilter(_EnvoyModel):
    name: str
    typed_config: dict[str, Any]

    @field_validator("typed_config")
    @classmethod
    def _typed_config_validates_against_type(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "@type" not in v:
            raise ValueError("network filter typed_config requires '@type'")
        type_url = v["@type"]
        # For known message types, parse-and-validate the inner shape so
        # template bugs (missing route_config, empty virtual_hosts,
        # contradictory route rules) are caught here rather than at runtime
        # in a real Envoy host. We keep the raw dict as the stored value
        # so any unknown extras pass through unchanged.
        if isinstance(type_url, str) and _HCM_TYPE_FRAGMENT in type_url:
            HttpConnectionManager.model_validate(v)
        return v


class FilterChain(_EnvoyModel):
    filters: list[NetworkFilter] = Field(min_length=1)


class ListenerConfig(_EnvoyModel):
    name: str
    address: Address
    filter_chains: list[FilterChain] = Field(min_length=1)


class StaticResources(_EnvoyModel):
    listeners: list[ListenerConfig] = Field(default_factory=list)
    clusters: list[ClusterConfig] = Field(default_factory=list)


class AdminConfig(_EnvoyModel):
    access_log_path: str | None = None
    address: Address


class EnvoyBootstrap(_EnvoyModel):
    """Top-level bootstrap config validator."""

    static_resources: StaticResources
    admin: AdminConfig | None = None


def validate_bootstrap(doc: dict[str, Any]) -> EnvoyBootstrap:
    """Parse and validate a bootstrap config dict. Raises pydantic
    ValidationError with a structured error path on any problem."""
    return EnvoyBootstrap.model_validate(doc)
