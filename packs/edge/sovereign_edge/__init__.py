"""Sovereign Edge Pack — Tier-4 service pack.

Provisions hardened edge compute (single nodes and small clusters) for
forward / disconnected / tactical sites, via the chassis `k8s-apply`
executor (edge K8s). Because edge compute sits outside the physical
perimeter, the pack enforces a higher integrity bar than the core:
FIPS-validated images (SI-7 / SR-11), measured-boot attestation
(SI-7(9)), and local-disk encryption (SC-28) are mandatory for
classified workloads.

Contributes:
  - two renderers / service types: edge-node, edge-cluster,
  - a `sovereign.pack.edge` OPA bundle (SI-7/SI-7(9)/SC-28/SR-11 +
    attestation-record obligation),
  - catalog entries published by the renderers.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import EdgeClusterParams, EdgeNodeParams
from .renderers import EdgeClusterRenderer, EdgeNodeRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-edge-pack"
    version = "0.1.0"
    description = "Hardened edge nodes and clusters with FIPS-image + attestation policy."

    renderers: ClassVar[list] = [EdgeNodeRenderer, EdgeClusterRenderer]
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "EdgeClusterParams",
    "EdgeClusterRenderer",
    "EdgeNodeParams",
    "EdgeNodeRenderer",
    "Pack",
]
