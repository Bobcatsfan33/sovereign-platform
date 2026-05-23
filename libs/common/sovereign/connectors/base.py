"""Abstract base class for connector implementations.

A connector is a strongly-typed adapter to an external data source —
S3, GitHub, SharePoint, Confluence, Elastic, Splunk, ServiceNow, local
filesystem, etc. It exposes a uniform lifecycle (connect, list_resources,
ingest, health_check) so packs and services can consume any source
through one interface.

Concrete connectors live in the chassis (S3Connector, GitHubConnector)
or in service packs. Auth state (the client returned by `connect()`)
lives on the instance, set during `connect()` and used by the other
methods. Connectors are not reentrant across credentials — make one
instance per (credentials, target) pair.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .types import (
    ConnectionResult,
    ConnectorCredentials,
    HealthStatus,
    IngestOptions,
    IngestResult,
    ResourceDescriptor,
)


class BaseConnector(ABC):
    """Implement once per external system. Subclasses must set
    `connector_type` — it's the key under which the registry stores the
    *class* (the platform instantiates per (tenant, credentials) pair)."""

    #: Stable identifier for the kind of system this connector adapts.
    connector_type: ClassVar[str]

    @abstractmethod
    async def connect(self, credentials: ConnectorCredentials) -> ConnectionResult:
        """Authenticate and build any internal client state. Subsequent
        method calls assume connect() ran successfully."""
        raise NotImplementedError

    @abstractmethod
    async def list_resources(
        self, filters: dict | None = None
    ) -> list[ResourceDescriptor]:
        """List resources the authenticated principal can see. `filters`
        are connector-specific (S3: {'bucket': ..., 'prefix': ...};
        GitHub: {'org': ..., 'visibility': 'public'|'private'})."""
        raise NotImplementedError

    @abstractmethod
    async def ingest(
        self, resource: ResourceDescriptor, options: IngestOptions
    ) -> IngestResult:
        """Pull `resource` from the source and stage it in the platform's
        S3 (per `options.destination_bucket`/`destination_prefix`)."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Cheap round-trip to the upstream system to verify auth and
        reachability. Called by the connector watchdog (Phase 3+) and
        surfaced on /healthz of services that use this connector."""
        raise NotImplementedError

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None) and not getattr(
            cls, "connector_type", None
        ):
            raise TypeError(
                f"{cls.__name__} must declare a class-level `connector_type` string"
            )
