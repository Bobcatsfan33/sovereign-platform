"""Multi-Cloud pack domain models — cloud accounts + landing zones.

Provisions cloud-account baselines and landing zones via Terraform
(reusing the executor the Data pack established). The pack's compliance
value is region-residency enforcement and mandatory governance tagging
across AWS GovCloud / Azure Gov / GCP — the same approved-region set the
base gov_region policy already knows, extended to whole accounts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CloudProvider = Literal["aws-govcloud", "azure-gov", "gcp"]
Classification = Literal["U", "CUI", "SECRET"]

# Approved government regions per provider (mirrors the base bundle's
# gov_region set; extended with Azure Gov + a GCP gov-adjacent region).
APPROVED_REGIONS: dict[str, frozenset[str]] = {
    "aws-govcloud": frozenset({"us-gov-west-1", "us-gov-east-1"}),
    "azure-gov": frozenset({"usgovvirginia", "usgovarizona"}),
    "gcp": frozenset({"us-central1", "us-east4"}),
}


class CloudAccountParams(BaseModel):
    """Baseline configuration for a managed cloud account/subscription."""

    provider: CloudProvider = "aws-govcloud"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    # CM-2: baseline guardrails (SCPs / Azure Policy / Org Policy).
    guardrails_enabled: bool = True
    # AU-2: org-level audit trail (CloudTrail / Activity Log / Audit Logs).
    org_audit_enabled: bool = True


class LandingZoneParams(BaseModel):
    """A multi-account landing zone (networking + baseline accounts)."""

    provider: CloudProvider = "aws-govcloud"
    region: str = "us-gov-west-1"
    classification: Classification = "CUI"
    account_count: int = Field(default=3, ge=1, le=100)
    # SC-7: hub-and-spoke with a managed boundary.
    network_boundary: bool = True


def region_is_approved(provider: str, region: str) -> bool:
    return region in APPROVED_REGIONS.get(provider, frozenset())
