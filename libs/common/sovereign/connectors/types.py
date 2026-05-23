"""Shared data types for the connector subsystem.

`ConnectorCredentials` is intentionally permissive (a `kind` discriminator
plus a free `data` dict). Each connector knows what keys to expect under
`data` and validates them in `connect()`. In production, `data` is
populated from the secrets layer (Vault) and never stored in DynamoDB or
S3 — see Phase 1 task 1.5.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ConnectorCredentials(BaseModel):
    """Credentials passed into `BaseConnector.connect()`.

    Examples:
        kind='aws_access_key', data={'access_key_id': ..., 'secret_access_key': ...}
        kind='aws_iam_role',   data={'role_arn': ...}
        kind='github_pat',     data={'token': ..., 'host': 'api.github.com'}
        kind='github_app',     data={'app_id': ..., 'installation_id': ..., 'private_key_pem': ...}
        kind='sharepoint_oauth', data={'tenant_id': ..., 'client_id': ..., 'client_secret': ...}
    """

    kind: str
    data: dict[str, Any] = Field(default_factory=dict, repr=False)


class ConnectionResult(BaseModel):
    """Returned by `BaseConnector.connect()`. `principal` identifies the
    authenticated entity (account number, user login, app name)."""

    ok: bool
    principal: str = ""
    detail: str = ""


class ResourceDescriptor(BaseModel):
    """A single addressable resource visible through the connector — a
    bucket, an object, a repo, a file, an index, etc.

    `resource_id` is opaque to the platform but stable across calls — the
    connector uses it as the lookup key in `ingest()`. `kind` is a hint
    for callers (e.g. RAG ingestion treats 'directory' resources as
    expandable, 'file' resources as leaf items)."""

    connector_type: str
    resource_id: str
    name: str
    kind: str = ""
    size_bytes: int | None = None
    last_modified: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestOptions(BaseModel):
    """Per-ingest controls. `destination_bucket` and `destination_prefix`
    select where in the platform's staging area the connector streams
    the data. `filters` are connector-specific (e.g. {'extension': '.md'})."""

    destination_bucket: str
    destination_prefix: str = ""
    max_size_bytes: int | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class IngestResult(BaseModel):
    ok: bool
    items_count: int = 0
    bytes_transferred: int = 0
    staged_paths: list[str] = Field(default_factory=list)
    detail: str = ""


class HealthStatus(BaseModel):
    ok: bool
    latency_ms: float | None = None
    message: str = ""
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
