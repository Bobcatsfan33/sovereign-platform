"""Edge pack domain models — edge nodes + edge clusters.

Provisions hardened edge compute (single nodes and small K3s-style
clusters) for disconnected / tactical / forward sites. Deploys via the
chassis `k8s-apply` executor (edge K8s). The compliance value is the
supply-chain / boot-integrity policy: FIPS-validated images and measured
boot (attestation) are mandatory for classified edge workloads.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Classification = Literal["U", "CUI", "SECRET"]


class EdgeNodeParams(BaseModel):
    """A single hardened edge node."""

    namespace: str = "sovereign-edge"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    # SI-7 / SR-11: only FIPS-validated, signed images.
    fips_image: bool = True
    # SI-7(9): measured boot / remote attestation.
    attestation_required: bool = True
    # SC-28: encrypt local storage (edge sites are physically exposed).
    disk_encryption: bool = True


class EdgeClusterParams(BaseModel):
    """A small edge cluster (K3s-style) of hardened nodes."""

    namespace: str = "sovereign-edge"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    node_count: int = Field(default=3, ge=1, le=50)
    fips_image: bool = True
    attestation_required: bool = True
    # AC-4: edge clusters operate disconnected; require store-and-forward
    # rather than always-on connectivity to the core.
    offline_mode: bool = True
