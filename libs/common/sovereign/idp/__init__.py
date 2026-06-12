"""IdP integration — OIDC token verification + group-to-role sync.

Phase 3 task 3.5. Phase 3 baseline shipped HS256 dev tokens via
`tenancy.jwt_auth.mint_dev_token`; this module is the production swap-
in: discover an OIDC provider's JWKS, verify RS256 tokens against it,
and turn IdP group claims into chassis RoleBindings.

SAML 2.0 (PIV/CAC) is documented in docs/idp-integration.md but not
implemented here — the dependency surface is large and the typical
deployment puts a SAML→OIDC gateway in front of the chassis (ICAM,
Login.gov, Azure AD GCC) so OIDC alone suffices for the chassis.

Public surface::

    from sovereign.idp import OidcVerifier, sync_groups_to_roles
"""

from .group_sync import sync_groups_to_roles
from .oidc import (
    OidcVerifier,
    get_oidc_verifier,
    reset_oidc_verifier,
    set_oidc_verifier,
)

__all__ = [
    "OidcVerifier",
    "get_oidc_verifier",
    "reset_oidc_verifier",
    "set_oidc_verifier",
    "sync_groups_to_roles",
]
