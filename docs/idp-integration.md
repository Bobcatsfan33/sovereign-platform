# IdP integration

The Sovereign Platform broker accepts two token shapes:

1. **HS256 dev tokens** signed with `DEV_JWT_SECRET`. Used by local dev,
   tests, and `tools/mint_jwt.py`. Never enabled in production.
2. **RS256 / ES256 OIDC tokens** verified against an IdP's JWKS via
   `sovereign.idp.OidcVerifier`. This is the production path.

For SAML 2.0 (PIV/CAC), the recommended pattern is a SAML→OIDC gateway
in front of the chassis. ICAM, Login.gov, and Azure AD GCC all expose
OIDC endpoints; many on-prem agency IdPs front-end SAML with one of
these. The chassis intentionally does NOT bundle a SAML stack — it
keeps the dependency surface small and avoids the patch burden of
xmlsec, lxml, and a SAML metadata parser.

## Common government IdPs

### Login.gov

Self-service signup at <https://developer.login.gov/>. Configure a new
"Service Provider" with:

| Field | Value |
| --- | --- |
| Issuer | `urn:gov:gsa:openidconnect.profiles:sp:sso:<agency>:<app>` |
| Login redirect URIs | `https://broker.<agency>.gov/auth/callback` |
| Logout redirect URIs | `https://broker.<agency>.gov/auth/logout` |
| Identity protocol | OIDC PKCE |
| IAL | IAL1 (basic) or IAL2 (verified) per program need |

Then configure the chassis:

```bash
OIDC_ISSUER_URL=https://secure.login.gov
OIDC_AUDIENCE=urn:gov:gsa:openidconnect.profiles:sp:sso:treasury:sovereign-platform
```

Login.gov does not currently surface group memberships in the `id_token`,
so role bindings are managed in the chassis directly (an operator
writes RoleBindings via `tools/grant_role.py`). For agencies that need
group-driven sync, front-end Login.gov with the agency directory.

### Azure AD Government (GCC / GCC High / DoD)

Register an application in your tenant's app registry, expose its
group claims, and grant your tenants the `groups` claim. Configure:

```bash
OIDC_ISSUER_URL=https://login.microsoftonline.us/<tenant-id>/v2.0
OIDC_AUDIENCE=<application-client-id>
OIDC_GROUPS_CLAIM=groups
```

Azure surfaces group **object IDs** by default, not human-readable
names. Translate them in your group→role map:

```python
GROUP_ROLE_MAP = {
    "f47ac10b-58cc-4372-a567-0e02b2c3d479": Role.agency_admin,
    "12345678-90ab-cdef-1234-567890abcdef": Role.program_team,
}
```

For DoD deployments use `login.microsoftonline.us` for GCC and
`login.microsoftonline.us` with the DoD tenant id for Impact Level 5
workloads.

### ICAM (Personal Identity Verification — PIV)

Stand a SAML→OIDC gateway: Keycloak or Authentik are common choices
both with FedRAMP-Moderate certified configurations. The gateway
consumes the PIV cert via mTLS, asserts the user's principal as a SAML
subject, and exchanges that for an OIDC ID token the chassis accepts
verbatim.

Recommended Keycloak realm config:
- Authentication flow: `Browser` → `PIV cert validation` → `SAML
  identity provider` → group enrichment from the agency directory
- Token format: `RS256`, kid rotated quarterly
- Group claim: `groups` array (list of group names)

## Group → role mapping

`sovereign.idp.group_sync.sync_groups_to_roles` materialises IdP groups
as `RoleBinding` records in DynamoDB. The chassis baseline mapping is in
`sovereign.tenancy.jwt_auth.DEFAULT_GROUP_ROLE_MAP`:

| IdP group | Chassis role |
| --- | --- |
| `sovereign-platform-admins` | `platform-admin` |
| `sovereign-agency-admins` | `agency-admin` |
| `sovereign-bureau-admins` | `bureau-admin` |
| `sovereign-program-teams` | `program-team` |
| `sovereign-auditors` | `auditor` |

Override per-deployment by passing your own dicts to
`sync_groups_to_roles(..., group_role_map=..., group_tenant_map=...)`.

For organisations whose IdP groups encode tenancy (e.g. `irs-cade2-leads`
should grant `program-team` at `cade2`), build a `group_tenant_map`
from your directory and a `group_role_map` from the role naming
convention.

## Verifier wiring (broker)

The broker imports `OidcVerifier` from `sovereign.idp`. To swap from
HS256 dev tokens to JWKS-based verification, set `OIDC_ISSUER_URL`
and `OIDC_AUDIENCE` in the environment. Phase 3 ships the verifier;
Phase 4 (UI) will add the OAuth2 authorisation-code-with-PKCE flow
the chassis UI uses to obtain tokens. Backend services that call
the chassis API are expected to use OIDC client-credentials grants
(Service Principals in Azure AD, Login.gov has a similar JWT-bearer
grant for trusted SPs).

## Audit trail

Every request logs `policy.evaluated` (Phase 2) and, when JWT-authed,
`rbac.denied` if the role check fails. The `actor` field is the
authenticated subject (the OIDC `sub` claim — for Login.gov this is
a pairwise pseudonymous identifier; for Azure AD it's the user's
object id; for SAML→OIDC gateways it's the PIV CN).
