"""Sovereign Blockchain Pack — Tier-4 service pack (final pack).

The most specialized pack: provisions permissioned distributed ledgers
(Hyperledger Fabric / Besu) on Kubernetes via the chassis `k8s-apply`
executor. Permissionless/public chains are intentionally excluded —
government use requires known, authorized validators. The policy bundle
enforces closed membership (AC-3), validator identity (IA-3), HSM-backed
key custody (SC-12), FIPS crypto (SC-13), and BFT consensus above a
validator-count threshold.

Contributes:
  - one renderer / service type: permissioned-ledger,
  - a `sovereign.pack.blockchain` OPA bundle (AC-3/IA-3/SC-12/SC-13 +
    validator-registration obligation),
  - a catalog entry published by the renderer.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import PermissionedLedgerParams
from .renderers import PermissionedLedgerRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-blockchain-pack"
    version = "0.1.0"
    description = "Permissioned distributed ledgers with membership, identity, and key-custody policy."

    renderers: ClassVar[list] = [PermissionedLedgerRenderer]
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "Pack",
    "PermissionedLedgerParams",
    "PermissionedLedgerRenderer",
]
