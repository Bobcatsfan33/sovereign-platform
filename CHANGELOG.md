# Changelog

All notable changes to the Sovereign Platform are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project aims to follow [Semantic Versioning](https://semver.org/).
Pre-1.0 alpha releases may make breaking changes between minor versions.

## [0.5.0-alpha] — 2026-06-04

First tagged release. Establishes versioning and release discipline for the
chassis and the service packs. This release covers everything from the initial
remediation through the full ten-pack catalog, enterprise/ATO hardening, and the
Epic 1 execution-and-drift work.

### Added — Service packs (all 10)

The platform now ships the full roadmap catalog as pip-installable wheels under
`packs/`, each discovered via the `sovereign.packs` entry point with its own
NIST-800-53-mapped OPA bundle:

- **AI** — `inference-endpoint`, `rag-workspace` (k8s) — AC-4/SC-8/SC-28/SI-12.
- **Data** — `managed-database`, `vector-db` (terraform) — SC-28/CP-9/SI-12.
- **SecOps** — `siem-workspace`, `log-pipeline` (k8s) — AU-9/AU-10/AU-11/SI-4.
- **Identity** — `idp-broker`, `scim-bridge` (config) — IA-2/IA-2(1)/IA-2(12)/IA-4/IA-8.
- **Multi-Cloud** — `cloud-account`, `landing-zone` (terraform) — AC-4/CM-2/SC-7/AU-2.
- **Edge** — `edge-node`, `edge-cluster` (k8s) — SI-7/SI-7(9)/SC-28/SR-11.
- **Comms** — `secure-email`, `secure-chat` (config) — SC-8/SC-13/AU-11/AC-4.
- **Blockchain** — `permissioned-ledger` (k8s) — AC-3/IA-3/SC-12/SC-13.
- **FinOps** — `budget`, `chargeback-report` (metering) — SA-2/PM-3/AU-6.

### Added — Chassis capabilities

- **Deployment executors** (`k8s-apply`, `terraform-apply`, `helm-upgrade`,
  `webhook`, `envoy-snapshot`) with a registry; renderers stay pure and delegate
  apply to the executor dispatcher.
- **Drift detection (ADR-0004)** — executor `diff()` (`kubectl diff`,
  `terraform plan -detailed-exitcode`), `diff_manifest()` aggregation, control-plane
  `POST /diff`, broker `_refresh_drift()`, and a periodic reconciler
  (`RECONCILE_INTERVAL_SECONDS`, default off) that re-converges drifted instances.
  Detection is fail-safe: an unreachable backend reports `unknown`, never a false drift.
- **Policy obligation enforcement** — the layered OPA decision aggregates pack/tenant
  `obligations`; the broker enforces them fail-closed at provision time
  (`obligation.enforced` / `obligation.failed` audit events).
- **OSB async provisioning** — `?accepts_incomplete=true` returns `202` and finalises
  apply in the background; `last_operation` exposes OSB-spec state. Default stays synchronous.
- **SecretsProvider** abstraction (env default; AWS Secrets Manager provider available).
- **Runtime pack OPA-bundle loading** — `collect_policy_bundle_dirs()`, surfaced on `/healthz`.
- **Lifecycle state machine** — operation IDs, terminal OSB states, reconciliation
  status, and a manual `POST /v2/reconcile`.

### Added — Security & operations hardening

- Constant-time bearer comparison; `broker_trust_basic_auth` gate on the Basic-auth
  RBAC bypass; `strict_secrets` production fail-closed; token-bucket rate limiting on
  all services; durable audit disk spool; signed/hash-chained audit with retention TTL;
  Prometheus `/metrics`; CI SBOM/SCA/cosign supply-chain steps; STIG/Packer/Salt scaffolding.
- ATO evidence track: SSP scaffold, POA&M, boundary + data-flow docs, tenant inventory
  index, deny-spike monitor, hourly continuous-monitor job.

### Added — Engineering / docs

- ADRs 0001–0004 (boundary, service identity & secrets, execution & reconciliation,
  canonical apply path & drift detection).
- `docs/enterprise-roadmap.md` — re-baselined roadmap mapped to the verified repo state.
- README documents all 10 packs; `make lint`/`make fmt` cover `packs/`.

### Fixed

- Root cause of "doesn't run green out of the box": Makefile now auto-detects Python
  3.11–3.13 with a fail-fast guard.
- FastAPI `lifespan` migration (off deprecated `on_event`).
- Portal image: patched libxml2 CVE-2026-6732 (time-boxed, architecture-aware).
- CI: Python 3.11/3.12/3.13 test matrix; OPA gate over base + every pack bundle.

### Known limitations (tracked for later epics)

- Insecure dev defaults still exist (`dev_bearer_token="dev-token"`, `minioadmin` in
  local compose); the production safety check logs/aborts but the defaults remain. **Do
  not deploy to a shared environment until Epic 2 (zero-trust auth & secrets) lands.**
- Executors and `diff()` shell out to real CLIs but are not exercised against live
  infrastructure in CI; a real pilot run is pending.
- Epics E2–E7 (zero-trust, production IaC/HA/DR, data durability, observability depth,
  ATO authorization, GA hardening) remain open — see `docs/enterprise-roadmap.md`.

[0.5.0-alpha]: https://github.com/Bobcatsfan33/sovereign-platform/releases/tag/v0.5.0-alpha
