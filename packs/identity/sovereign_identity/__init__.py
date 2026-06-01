"""Sovereign Identity Pack — Tier-3 service pack.

Productizes the chassis's existing OIDC verifier and tenancy/RBAC layer
as self-service-bindable service types: an IdP broker (bind an agency
OIDC/SAML provider with MFA + assurance enforcement) and a SCIM bridge
(sync directory groups to chassis RoleBindings). Config-driven — no new
deployment backend (like FinOps) — its value is the IA-family policy
bundle that gates how agency identity sources may connect.

Contributes:
  - two renderers / service types: idp-broker, scim-bridge,
  - a `sovereign.pack.identity` OPA bundle (IA-2/IA-2(1)/IA-2(12)/IA-4/
    IA-5/IA-8 + identity-binding audit obligation),
  - catalog entries published by the renderers.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack

from .models import IdpBrokerParams, ScimBridgeParams
from .renderers import IdpBrokerRenderer, ScimBridgeRenderer

_POLICY_DIR = Path(__file__).parent / "policies"


class Pack(BasePack):
    name = "sovereign-identity-pack"
    version = "0.1.0"
    description = "IdP broker and SCIM bridge over the chassis identity plane, with IA-family policy."

    renderers: ClassVar[list] = [IdpBrokerRenderer, ScimBridgeRenderer]
    connectors: ClassVar[list] = []
    policy_bundles: ClassVar[list[Path]] = [_POLICY_DIR]


__all__ = [
    "IdpBrokerParams",
    "IdpBrokerRenderer",
    "Pack",
    "ScimBridgeParams",
    "ScimBridgeRenderer",
]
