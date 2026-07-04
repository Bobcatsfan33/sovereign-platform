"""Sovereign Comms Pack — Tier-4 service pack.

Provisions governed communication channels (secure email relay, secure
chat workspace) bound to agency providers. Config-driven (no new
executor, like Identity/FinOps) — the value is the policy bundle
enforcing transmission confidentiality (SC-8), FIPS cryptography
(SC-13), message retention (SI-12 / AU-11), and federation controls
(AC-4).

Contributes:
  - two renderers / service types: secure-email, secure-chat,
  - a `sovereign.pack.comms` OPA bundle (SC-8/SC-13/AU-11/AC-4 +
    archive-metadata obligation),
  - catalog entries published by the renderers.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import SecureChatParams, SecureEmailParams
from .renderers import SecureChatRenderer, SecureEmailRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-comms-pack"
    version = "0.1.0"
    description = "Secure email and chat channels with transmission-confidentiality and retention policy."
    maturity = "lab"
    maturity_summary = "Design-complete pack that needs provider-specific email/chat integration."

    renderers: ClassVar[list] = [SecureEmailRenderer, SecureChatRenderer]
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "Pack",
    "SecureChatParams",
    "SecureChatRenderer",
    "SecureEmailParams",
    "SecureEmailRenderer",
]
