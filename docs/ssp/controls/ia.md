# IA — Identification and Authentication

## Control mapping

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **IA-2** Identification and Authentication (Organizational Users) | implemented (via Phase 3.5 OIDC) | Human callers authenticate via the agency IdP through OIDC. The `_decode` helper verifies the JWT signature against the IdP's JWKS, the `iss` claim against the configured issuer, and the `aud` claim against the configured audience. | `libs/common/sovereign/idp/oidc.py`; `libs/common/sovereign/tenancy/jwt_auth.py::_decode`; `tests/test_idp.py` |
| **IA-2(1)** MFA for Privileged Accounts | implemented + inherited | The agency IdP performs MFA and asserts the result in the OIDC `amr` claim. For JWT state-changing actions, the broker passes `amr` to OPA and `policies/base/authentication.rego` denies the request unless `mfa` is present. | `apps/broker/app/main.py::_evaluate_policy`; `policies/base/authentication.rego`; `policies/tests/authentication_test.rego` |
| **IA-2(2)** MFA for Non-Privileged Accounts | inherited | Same as IA-2(1). |  |
| **IA-2(8)** Replay-Resistant Authentication | implemented | JWTs include `iat` + `exp`; the verifier rejects tokens past `exp`. The portal OIDC callback uses authorization code + PKCE, validates `state`, `iss`, `aud`, `nonce`, and `exp`, and stores only the token endpoint result. JWKS cache refresh honors IdP `max-age` and uses bounded stale keys during short IdP outages. | `libs/common/sovereign/idp/oidc.py`; `apps/portal/src/auth/oidc.ts`; `tests/test_idp.py`; `apps/portal/src/test/oidc.test.ts` |
| **IA-3** Device Identification and Authentication | inherited | Device posture is enforced at the agency endpoint (mTLS at the front-door gateway). The chassis does not bind sessions to device certificates directly. |  |
| **IA-4** Identifier Management | inherited | Principal identifiers come from the IdP `sub` claim and are immutable. Group identifiers come from the IdP `groups` claim and are mapped to chassis roles via the group-sync configuration. | `libs/common/sovereign/idp/group_sync.py` |
| **IA-5** Authenticator Management | inherited | Password / token lifecycle is the IdP's responsibility. The chassis only carries the dev-token sentinel (`dev-token`) which logs ERROR if active under `ENV=production`. | `libs/common/sovereign/settings.py::_DEV_SENTINELS`; `tests/test_settings.py::test_production_logs_warning_for_dev_defaults` |
| **IA-5(1)** Password-Based Authentication | implemented (OSB Basic only) | The OSB v2 spec requires Basic auth on `/v2/*`. The chassis verifies via `secrets.compare_digest` (constant-time). Credentials come from env vars (no defaults in production). | `apps/broker/app/main.py::identify` |
| **IA-5(2)** Public Key-Based Authentication | inherited | RS256/ES256 JWT verification via JWKS (Phase 3.5). | `libs/common/sovereign/idp/oidc.py::verify_with_jwks` |
| **IA-6** Authentication Feedback | implemented | Auth failures return RFC 7807 problem detail with the WWW-Authenticate header set to `Bearer realm="sovereign-platform"`. The detail message never reveals which field (username vs password vs token) was wrong. | `libs/common/sovereign/security.py::require_bearer`; `apps/broker/app/main.py::identify` |
| **IA-7** Cryptographic Module Authentication | inherited | Underlying TLS / JWT libraries are FIPS-validated through the agency-managed OpenSSL FIPS module (POA&M 5.4-A). |  |
| **IA-8** Identification and Authentication (Non-Organizational Users) | implemented (Basic + OIDC) | Non-organizational callers (federated agency partners) authenticate via the agency's federated identity provider; the same OIDC code path handles them. |  |
| **IA-11** Re-authentication | inherited | Session lifetime is the IdP-issued `exp` (typically 8 hours for human sessions, much shorter for service tokens). The portal `useAuth` hook re-prompts when a request returns 401. |  |
| **IA-12** Identity Proofing | inherited | Identity proofing happens at the IdP before any account exists. |  |

## High overlay

| Additional | Note |
| --- | --- |
| IA-2(11) MFA for Remote Access | JWT state-changing API calls now fail closed when IdP `amr` lacks `mfa`; remaining evidence is the agency IdP configuration export showing MFA is mandatory for remote users. |
| IA-4(4) Identifying Status | Add `tenant_active: true` check before any RBAC pass; pulled from the tenancy store. |
