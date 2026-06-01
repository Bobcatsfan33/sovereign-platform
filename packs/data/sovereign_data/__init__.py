"""Sovereign Data Platform Pack — Tier-2 service pack.

The Data pack is the chassis's first consumer of the `terraform-apply`
deployment executor (the AI pack used `k8s-apply`), proving the Step 0.2
executor abstraction generalises across backends with no change to the
renderer contract. Its renderers are pure: they emit Terraform JSON
config and a `terraform-apply` step the chassis applies.

Contributes:
  - two renderers / service types: managed-database, vector-db,
  - a `sovereign.pack.data` OPA bundle (SC-28 / CP-9 / SI-12 +
    classification-tag obligation),
  - catalog entries published by the renderers.

Discovery: installing this wheel into a chassis venv registers it via the
`sovereign.packs` entry point in pyproject.toml.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import ManagedDatabaseParams, VectorDbParams
from .renderers import ManagedDatabaseRenderer, VectorDbRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-data-pack"
    version = "0.1.0"
    description = "Managed databases and vector stores provisioned via Terraform, with data-protection policy."

    renderers: ClassVar[list] = [ManagedDatabaseRenderer, VectorDbRenderer]
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "ManagedDatabaseParams",
    "ManagedDatabaseRenderer",
    "Pack",
    "VectorDbParams",
    "VectorDbRenderer",
]
