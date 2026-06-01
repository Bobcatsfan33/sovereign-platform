"""Sovereign AI Pack — flagship Tier-1 service pack.

The AI pack is the first pack to exercise the chassis's deployment
executors (Step 0.2): its renderers are *pure* and emit Kubernetes
`k8s-apply` manifests that the chassis applies, so the pack carries no
apply logic of its own. It is also the first producer of
`PolicyDecision.obligations` — its OPA bundle attaches PII-redaction and
model-provenance obligations the broker enforces on allow.

Contributes:
  - two renderers / service types: inference-endpoint, rag-workspace,
  - a `sovereign.pack.ai` OPA bundle (AC-4 / SC-8 / SC-28 / SI-12 +
    obligations),
  - catalog entries published by the renderers' catalog_entry().

Discovery: installing this wheel into a chassis venv registers it via the
`sovereign.packs` entry point in pyproject.toml — no chassis changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import InferenceEndpointParams, RagWorkspaceParams
from .renderers import InferenceEndpointRenderer, RagWorkspaceRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-ai-pack"
    version = "0.1.0"
    description = "Managed inference endpoints and RAG workspaces with model-governance policy."

    renderers: ClassVar[list] = [InferenceEndpointRenderer, RagWorkspaceRenderer]
    connectors: ClassVar[list] = []  # reuses chassis S3/GitHub connectors for RAG ingestion
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "InferenceEndpointParams",
    "InferenceEndpointRenderer",
    "Pack",
    "RagWorkspaceParams",
    "RagWorkspaceRenderer",
]
