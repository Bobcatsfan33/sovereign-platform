# Plan of Action and Milestones (POA&M)

> Phase 5 task 5.6. Documents the known gaps between the chassis as
> shipped and the full Moderate-baseline expectation. Each item carries
> a severity, an owner, a target date, and the source (SSP control,
> assessor finding, security test result, or roadmap task).

Severity scale:

- **High** — gap blocks production use at Moderate baseline.
- **Medium** — gap reduces evidence quality or operational posture but
  has a documented compensating control.
- **Low** — gap is cosmetic, future-hardening, or only relevant under
  the High overlay.

## Open items

| ID | Severity | Title | Source | Owner | Target | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 5.4-A | Medium | Switch chassis container base from `python:3.11-slim` to a FIPS-validated Python build | SC-13, IA-7 | Platform Eng | 2026-Q4 | open |
| 5.4-CVE-OPENSSL | Medium | 7 OpenSSL CVEs (CVE-2025-15467, CVE-2025-69421, CVE-2026-28387 .. -28390, CVE-2026-31789) ignored in `.trivyignore` pending Debian point-release availability | SC-13, SI-2 | Platform Eng | 2026-Q3 | open — quarterly review next 2026-08 |
| 5.4-CVE-libxml2 | Medium | Portal `nginx:1.27.4-alpine` inherited CVE-2026-6732 in libxml2 — base bumped to `nginx:1.30.3-alpine`; verify fix ships on x86_64 and remove `.trivyignore` entry | SI-2, SA-22 | Platform Eng | 2026-Q3 | mitigating — verify CI green then close |
| 5.4-CVE-GNUTLS | Medium | 7 GnuTLS CVEs ignored in `.trivyignore`; gnutls is not linked by any chassis service | SC-13, SI-2 | Platform Eng | 2026-Q3 | open — quarterly review next 2026-08 |
| 5.4-CVE-MISC | Low | 10 system-package CVEs (gnupg, libcap, sqlite, xz, pam, perl, setuptools, wheel) ignored in `.trivyignore`; build-time / out-of-call-graph for chassis runtime | SI-2 | Platform Eng | 2026-Q3 | open — quarterly review next 2026-08 |
| 5.4-C | Low | Switch to chainguard/python distroless base to eliminate the inherited CVE allow-list entirely | SC-13, SA-22 | Platform Eng | 2026-Q4 | open — depends on FIPS validation status of chainguard's Python build |

## Closed items

| ID | Closed in | Notes |
| --- | --- | --- |
| 0.1 | 2026-05-23 (commit `09a9c1b`) | Repo consolidation; governance models merged. |
| 0.2 | 2026-05-23 (commit `017de99`) | Dedicated audit service replaced inline ClickHouse coupling. |
| 0.5 | 2026-05-23 (commit `9033eee`) | RFC 7807 problem detail across every endpoint. |
| 0.6 | 2026-05-23 (commit `6072ea0`) | Pydantic Envoy-v3 validation gate before S3 write. |
| 0.7 | 2026-05-23 (commit `9fbb0d3`) | Hardcoded credentials removed; production sentinel check added. |
| 5.4-B | 2026-05-24 (commit `c403194`) | OPA image pinned to `openpolicyagent/opa:1.6.0-rootless`; no `:latest-rootless` dependency remains. |
| 2.* | 2026-05-23 (commits `cb624ae` + `2bd7e2b`) | Policy engine, layered decision, broker gate, decision audit. |
| 3.* | 2026-05-23 (commits `2ff6b88` / `4075e85` / `18473b6`) | Tenancy, RBAC, JWT, OIDC, quota. |
| 4.* | 2026-05-24 (commits `e6d78c7` / `99a7be5`) | Portal SPA + broker portal endpoints + axe-clean a11y. |
| 3.5-A | Sprint 5 branch | `OidcVerifier` honors JWKS `max-age` and uses bounded stale keys during IdP outages. |
| 5.2-G | Sprint 5 branch | `policies/base/authentication.rego` requires `mfa` in OIDC `amr` for JWT state-changing actions. |
| 5.2-D | Sprint 6 branch | Audit rows can be signed with an Ed25519 service-account key; production can require signing key material at startup. |
| 5.2-C | Sprint 7 branch | `AUDIT_RETENTION_DAYS` drives ClickHouse TTL creation/migration and is exposed in the production manifest. |
| 5.2-E | Sprint 8 branch | PR template requires security-reviewer pass, control-impact review, and security-relevant tests. |
| 0.5-A | Sprint 8 branch | No `@app.on_event`/`on_event(` usage remains under `apps/` or `libs/`; services use lifespan handlers where startup work exists. |
| 5.2-B | Sprint 9 branch | Continuous monitor detects deny spikes per actor via audit-service `/events?decision=deny`. |
| 1.7-A | Sprint 9 branch | `sovereign_instances` now has an `organization_guid` GSI used by tenant-scoped `list_instances`. |
| 5.2-A | Sprint 10 branch | NGINX front-door overlay applies RPS, burst, connection, TLS, and body-size controls to broker/audit routes. |
| 5.2-H | Sprint 10 branch | Kyverno admission overlay verifies cosign keyless signatures, digests, and SLSA provenance for chassis images. |
| 5.2-F | Sprint 13 branch | Portal OIDC uses authorization code + PKCE and validates stored `state`, returned `iss`, `aud`, `nonce`, and `exp` before accepting the token endpoint result. |

## How an assessor uses this file

1. Read the open items table top-to-bottom; each row maps to a control
   and a code-side or process-side remediation.
2. For each item, follow the linked control chapter to see what
   evidence currently exists and what's missing.
3. Items rated High block an authority-to-operate at Moderate baseline.
   There are currently zero High items.
