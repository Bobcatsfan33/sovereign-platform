"""Sovereign Multi-Cloud Pack — Tier-4 service pack.

Provisions governed cloud accounts and multi-account landing zones across
AWS GovCloud / Azure Gov / GCP via the chassis Terraform executor (the
Data pack proved `terraform-apply`; this pack reuses it across a
different provider surface). The compliance value is residency
enforcement extended from single resources (base gov_region) to whole
accounts, plus guardrail/boundary governance.

Contributes:
  - two renderers / service types: cloud-account, landing-zone,
  - a `sovereign.pack.multicloud` OPA bundle (AC-4/CM-2/SC-7/AU-2 +
    classification-tag obligation),
  - catalog entries published by the renderers.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import APPROVED_REGIONS, CloudAccountParams, LandingZoneParams
from .renderers import CloudAccountRenderer, LandingZoneRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-multicloud-pack"
    version = "0.1.0"
    description = "Governed cloud accounts and landing zones across GovCloud/Azure-Gov/GCP with residency policy."
    maturity = "lab"
    maturity_summary = "Design-complete pack that needs live multi-cloud landing-zone validation."

    renderers: ClassVar[list] = [CloudAccountRenderer, LandingZoneRenderer]
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "APPROVED_REGIONS",
    "CloudAccountParams",
    "CloudAccountRenderer",
    "LandingZoneParams",
    "LandingZoneRenderer",
    "Pack",
]
