"""Identity pack domain models — IdP broker + SCIM bridge.

The Identity pack productizes the chassis's existing OIDC verifier and
tenancy/RBAC layer as provisionable service types. It introduces no new
deployment backend (config-driven, like FinOps) — its value is binding
agency IdPs and SCIM directories to the chassis identity plane under
IA-family policy (MFA, PIV/CAC assurance, token lifetime).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Protocol = Literal["oidc", "saml"]
# NIST SP 800-63 Authenticator Assurance Levels.
AAL = Literal["aal1", "aal2", "aal3"]


class IdpBrokerParams(BaseModel):
    """Bind an agency identity provider to the chassis identity plane."""

    issuer_url: str = Field(min_length=1)
    protocol: Protocol = "oidc"
    audience: str = ""
    # IA-2(1): minimum authenticator assurance the bound IdP must attest.
    required_aal: AAL = "aal2"
    # IA-2: require MFA for all federated principals.
    require_mfa: bool = True
    # IA-2(12): accept PIV/CAC (x509) — common for federal agencies.
    allow_piv_cac: bool = True
    # Max access-token lifetime in minutes the broker will accept.
    max_token_minutes: int = Field(default=60, ge=1, le=1440)


class ScimBridgeParams(BaseModel):
    """Bind a SCIM 2.0 directory so group membership syncs to chassis
    RoleBindings (extends the existing group-to-role sync)."""

    endpoint_url: str = Field(min_length=1)
    sync_interval_minutes: int = Field(default=15, ge=1, le=1440)
    # IA-4: deprovision principals removed upstream.
    deprovision_on_remove: bool = True
