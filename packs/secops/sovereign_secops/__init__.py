"""Sovereign SecOps Pack — Tier-3 service pack.

Provisions security-monitoring infrastructure (SIEM workspace + log
pipeline) on Kubernetes via the chassis `k8s-apply` executor, and — its
real value — enforces the audit-family controls a SIEM exists to satisfy:
AU-9 (immutable audit storage), AU-10 (non-repudiation / signed records),
AU-11 (retention floor), SI-4 (monitoring). The base bundle already
anticipated `siem-workspace` in its storage/encryption sets.

Contributes:
  - two renderers / service types: siem-workspace, log-pipeline,
  - a `sovereign.pack.secops` OPA bundle (AU-9/AU-10/AU-11/SI-4 +
    self-monitor obligation),
  - catalog entries published by the renderers.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import LogPipelineParams, SiemWorkspaceParams
from .renderers import LogPipelineRenderer, SiemWorkspaceRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-secops-pack"
    version = "0.1.0"
    description = "SIEM workspaces and log pipelines with audit-family (AU-*) policy enforcement."
    maturity = "preview"
    maturity_summary = "Ready for security-operations pilot use with buyer SIEM/log retention assumptions."

    renderers: ClassVar[list] = [SiemWorkspaceRenderer, LogPipelineRenderer]
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "LogPipelineParams",
    "LogPipelineRenderer",
    "Pack",
    "SiemWorkspaceParams",
    "SiemWorkspaceRenderer",
]
