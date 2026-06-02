"""Comms pack domain models — secure email + secure chat.

Provisions governed communication channels (email relay, chat workspace)
bound to agency providers. Config-driven (no new executor, like Identity)
— the value is the policy bundle enforcing transmission confidentiality
(SC-8), FIPS crypto (SC-13), and message retention (SI-12 / AU-11).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Classification = Literal["U", "CUI", "SECRET"]

# FIPS 140-validated TLS suites (mirrors the base crypto bundle's set).
FIPS_TLS_SUITES: frozenset[str] = frozenset(
    {
        "TLS_AES_256_GCM_SHA384",
        "TLS_AES_128_GCM_SHA256",
        "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
        "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
    }
)


class SecureEmailParams(BaseModel):
    """A governed email relay bound to an agency mail provider."""

    provider: str = "m365-gcc-high"
    classification: Classification = "CUI"
    # SC-8: TLS required on the relay.
    tls_required: bool = True
    # SC-13: FIPS-validated cipher suite.
    cipher_suite: str = "TLS_AES_256_GCM_SHA384"
    # SI-12 / AU-11: message retention in days.
    retention_days: int = Field(default=2555, ge=1, le=36500)  # ~7y default
    # SC-8(1): DLP scan on egress.
    dlp_enabled: bool = True


class SecureChatParams(BaseModel):
    """A governed chat workspace."""

    provider: str = "teams-gcc-high"
    classification: Classification = "CUI"
    tls_required: bool = True
    cipher_suite: str = "TLS_AES_256_GCM_SHA384"
    retention_days: int = Field(default=365, ge=1, le=36500)
    # AC-4: external federation off by default for classified channels.
    external_federation: bool = False


def is_fips_suite(suite: str) -> bool:
    return suite in FIPS_TLS_SUITES
