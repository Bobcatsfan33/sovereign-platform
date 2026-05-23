"""Connector subsystem — pluggable external data-source clients.

Connectors are a cross-cutting platform capability: the RAG Pack ingests
docs through them, the Data Platform uses them as pipeline sources, the
SecOps Pack uses them for log collection, the Enterprise Search
capability uses them for indexing. Placing them in the base chassis lets
any pack declare connector dependencies; the platform manages auth,
health monitoring, and credential rotation centrally.

Public surface:

    from sovereign.connectors import (
        BaseConnector,
        ConnectorCredentials,
        ResourceDescriptor,
        IngestOptions,
        IngestResult,
        HealthStatus,
        ConnectionResult,
        registry,
        get_connector,
        register_connector,
    )
"""

from .base import BaseConnector
from .github import GitHubConnector
from .registry import get_connector, register_connector, registry
from .s3 import S3Connector
from .types import (
    ConnectionResult,
    ConnectorCredentials,
    HealthStatus,
    IngestOptions,
    IngestResult,
    ResourceDescriptor,
)

# Pre-register the two chassis connectors so any service that imports
# `sovereign.connectors` sees them. Service packs add more connectors
# via their own register_connector calls (Phase 1 task 1.9).
register_connector(S3Connector)
register_connector(GitHubConnector)

__all__ = [
    "BaseConnector",
    "ConnectionResult",
    "ConnectorCredentials",
    "GitHubConnector",
    "HealthStatus",
    "IngestOptions",
    "IngestResult",
    "ResourceDescriptor",
    "S3Connector",
    "get_connector",
    "register_connector",
    "registry",
]
