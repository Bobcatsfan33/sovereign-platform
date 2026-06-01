"""SecOps pack domain models — SIEM workspaces + log pipelines.

The SecOps pack provisions security-monitoring infrastructure on
Kubernetes (reusing the `k8s-apply` executor the AI pack established) and
enforces the audit-family controls (AU-*) that a SIEM exists to satisfy:
minimum log retention, tamper-evident (immutable) storage, and a sane
ingestion path. The base bundle anticipated this pack — `siem-workspace`
already appears in its storage-backed / encryption sets.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Backend = Literal["elastic", "opensearch", "splunk"]
Classification = Literal["U", "CUI", "SECRET"]

# AU-11: minimum audit-record retention. Federal baselines commonly
# require 90 days online + 1 year archived; we enforce the 90-day online
# floor for classified workspaces.
MIN_RETENTION_DAYS_CLASSIFIED = 90


class SiemWorkspaceParams(BaseModel):
    """Provisioning parameters for a managed SIEM workspace."""

    backend: Backend = "opensearch"
    namespace: str = "sovereign-secops"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    retention_days: int = Field(default=90, ge=1, le=3650)
    # AU-9: immutable / tamper-evident storage (WORM).
    immutable_storage: bool = True
    encryption_at_rest: bool = True
    hot_nodes: int = Field(default=3, ge=1, le=100)


class LogPipelineParams(BaseModel):
    """Provisioning parameters for a log-collection pipeline feeding a
    SIEM workspace. Sources are chassis connector ids (s3, github, ...)."""

    name: str = Field(min_length=1)
    namespace: str = "sovereign-secops"
    sinks: list[str] = Field(default_factory=lambda: ["siem"])
    sources: list[str] = Field(default_factory=list)
    classification: Classification = "CUI"
    # AU-10: non-repudiation — sign forwarded records.
    sign_records: bool = True
