"""Blockchain pack domain models — permissioned ledgers.

The most specialized pack: provisions permissioned distributed ledgers
(Hyperledger Fabric / Besu) on Kubernetes via the chassis `k8s-apply`
executor. Permissionless/public chains are intentionally not offered —
gov use requires known, authorized validators. The policy value is
membership control (AC-3), validator identity (IA-3), and HSM-backed key
custody (SC-12).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LedgerPlatform = Literal["fabric", "besu"]
ConsensusType = Literal["raft", "ibft2", "qbft"]
Classification = Literal["U", "CUI", "SECRET"]


class PermissionedLedgerParams(BaseModel):
    """A permissioned distributed ledger network."""

    platform: LedgerPlatform = "fabric"
    consensus: ConsensusType = "raft"
    namespace: str = "sovereign-ledger"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    validator_count: int = Field(default=4, ge=1, le=100)
    # AC-3: closed membership — only authorized orgs may join.
    permissioned: bool = True
    # IA-3: every validator authenticates with an issued identity.
    validator_identity_required: bool = True
    # SC-12: signing keys held in an HSM / KMS, not on disk.
    hsm_key_custody: bool = True
    # SC-13: FIPS-validated crypto for the ledger's signatures.
    fips_crypto: bool = True


# Byzantine-fault-tolerant consensus families (tolerate malicious nodes),
# vs crash-fault-tolerant (raft). BFT is required above a validator-count
# threshold where collusion risk warrants it.
BFT_CONSENSUS: frozenset[str] = frozenset({"ibft2", "qbft"})
BFT_REQUIRED_ABOVE = 7


def is_bft(consensus: str) -> bool:
    return consensus in BFT_CONSENSUS
