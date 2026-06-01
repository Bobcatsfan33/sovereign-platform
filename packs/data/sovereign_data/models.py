"""Data Platform pack domain models — managed databases + vector stores.

The Data pack provisions stateful data services via Terraform, so it is
the chassis's first consumer of the `terraform-apply` executor (the AI
pack used `k8s-apply`). Proving a second executor against the same
renderer contract is the point of this tier: it shows the Step 0.2
abstraction generalises beyond Kubernetes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Engine = Literal["postgres", "mysql"]
Classification = Literal["U", "CUI", "SECRET"]


class ManagedDatabaseParams(BaseModel):
    """Provisioning parameters for a managed relational database."""

    engine: Engine = "postgres"
    version: str = "16"
    storage_gb: int = Field(default=20, ge=10, le=65536)
    instance_class: str = "db.t3.medium"
    multi_az: bool = False
    namespace: str = "sovereign-data"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    encryption_at_rest: bool = True
    backup_retention_days: int = Field(default=7, ge=0, le=35)
    deletion_protection: bool = True


class VectorDbParams(BaseModel):
    """Provisioning parameters for a managed vector database."""

    store: Literal["pgvector", "qdrant", "milvus"] = "pgvector"
    storage_gb: int = Field(default=20, ge=10, le=65536)
    namespace: str = "sovereign-data"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    encryption_at_rest: bool = True


# Backup retention floor required for CUI/SECRET data (CP-9).
MIN_BACKUP_DAYS_CLASSIFIED = 7
