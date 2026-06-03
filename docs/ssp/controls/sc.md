# SC — System and Communications Protection

## Control mapping

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **SC-4** Information in Shared Resources | implemented | Tenancy isolation: every `AuditEvent`, `Usage` record, and `ServiceInstance` carries a `tenant_id`. The `AuthzResolver` rejects any cross-tenant read by a non-superuser. DynamoDB tables are partitioned by tenant id in the keys that carry one (`sovereign_usage`); single-key tables (`sovereign_instances`) filter in the broker before returning data. | `libs/common/sovereign/tenancy/authz.py`; `libs/common/sovereign/usage_store.py` |
| **SC-7** Boundary Protection | implemented | Each service exposes a single port. Bearer auth (or OSB Basic) is required on every non-/healthz endpoint. CORS is allow-listed to the portal origin only (`PORTAL_ORIGINS` env var). External egress from chassis services is limited to: control plane → S3, audit service → ClickHouse, broker → control plane / audit / OPA / DynamoDB. The agency's network policy enforces these flows. | `apps/broker/app/main.py`; `libs/common/sovereign/cors.py`; agency IaC (organizational) |
| **SC-7(3)** Access Points | implemented | The portal is the only browser-facing entry point. Programmatic callers come through the broker. Both sit behind the agency's TLS-terminating load balancer. |  |
| **SC-8** Transmission Confidentiality and Integrity | implemented | The `sovereign.base.transmission` OPA rule rejects any provisioning request that disables TLS on a network-facing service type. Service-pack-specific rules (AI Pack, Data Pack) extend this with stricter requirements (mTLS, client-cert auth). | `policies/base/transmission.rego`; `policies/tests/transmission_test.rego` |
| **SC-8(1)** Cryptographic Protection | implemented | The `sovereign.base.crypto` OPA rule rejects any non-FIPS-approved cipher suite on services that declare `cipher_suites`. The default allow-set covers TLS 1.2 + TLS 1.3 FIPS-approved suites. | `policies/base/crypto.rego` |
| **SC-12** Cryptographic Key Establishment and Management | inherited | TLS termination is at the agency's API gateway / KMS-backed key store. The chassis does not manage TLS private keys for tenant traffic — Envoy hosts retrieve their materials from the agency-managed secrets system at boot. |  |
| **SC-13** Cryptographic Protection | implemented (policy), POA&M for runtime module | See SC-8(1). FIPS-approved cipher enforcement is policy-based and verified by `policies/tests/crypto_test.rego::test_legacy_rc4_denies`. The chassis runtime still depends on the agency-selected FIPS-validated Python/OpenSSL base image; POA&M 5.4-A tracks that remaining base-image decision. | `policies/base/crypto.rego`; `docs/ssp/poam.md::5.4-A` |
| **SC-23** Session Authenticity | implemented | JWTs carry the agency-issued `iss`, `aud`, `iat`, `exp` claims. The `_decode` helper verifies signature + audience + expiry; the OIDC integration (Phase 3.5) does the same against the IdP's JWKS. The portal stores the token in `sessionStorage` (not `localStorage`) so credentials clear on tab close. | `libs/common/sovereign/tenancy/jwt_auth.py::_decode`; `apps/portal/src/hooks/useAuth.ts` |
| **SC-28** Protection of Information at Rest | implemented | The `sovereign.base.encryption_at_rest` policy rejects any provisioning request for a storage-backed service that doesn't set `encryption_at_rest: true`. DynamoDB and S3 themselves are encrypted at rest by the hosting environment (inherited). | `policies/base/encryption_at_rest.rego`; `policies/tests/encryption_at_rest_test.rego` |
| **SC-39** Process Isolation | implemented | Each chassis service runs as a separate container. Container images run as non-root (Phase 5.4). | `apps/*/Dockerfile` |
| **SC-45** System Time Synchronization | inherited | Container hosts sync NTP from the cloud platform's time service (AWS Time Sync Service, Azure Time Service). Documented in agency IaC. |  |

## High overlay

| Additional | Note |
| --- | --- |
| SC-8(2) Pre/Post Transmission Handling | Add Envoy filter chains that strip PII headers on egress for AI Pack inference endpoints. |
| SC-7(8) Route Traffic to Authenticated Proxy Servers | Front the chassis with an authenticated forward proxy at the agency border (organizational). |
