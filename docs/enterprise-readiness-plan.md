# Enterprise Readiness Plan

## Current Readiness

Sovereign Platform is a strong reference implementation for a
compliance-native self-service infrastructure control plane. It is not yet
enterprise deployable. The first production-ready milestone is concentrated in
five areas:

1. Execution and reconciliation.
2. Service identity, secrets, and production auth.
3. Production infrastructure, HA, and DR.
4. Observability and operations.
5. A real authorization package with evidence and continuous monitoring.

## Sprint Sequence

### Sprint 0: Foundations

Objective: lock decisions and add security/supply-chain guardrails that later
sprints depend on.

Exit criteria:

- Authorization boundary ADR accepted.
- Service identity and secrets ADR accepted.
- Execution and reconciliation ADR accepted.
- Production defaults fail closed for development sentinel secrets.
- Production Basic-auth RBAC bypass defaults off.
- Python dependency audit and CycloneDX SBOM generation run in CI.

### Sprint 1A: Execution Lifecycle Hooks

Objective: make the existing renderer/executor lifecycle explicit in service
startup and deprovision flows.

Exit criteria:

- Standard chassis executors are registered at broker/control-plane startup.
- Health checks expose registered executor kinds.
- Control-plane render continues to invoke render, validate, and apply.
- Deprovision invokes renderer teardown.
- Teardown emits audit evidence but remains best-effort.

### Sprint 1B: Reconciliation Controller

Objective: move from one-shot lifecycle calls to convergent desired-state
operations.

Exit criteria:

- Apply failures set terminal failed OSB state with failed step detail.
- One pilot pack proves end-to-end create/update/delete in a non-emulator
  environment.
- Operation state includes retry-safe IDs, failure reason, and apply outputs.
- Drift detection identifies actual-state mismatch for the pilot pack.
- Reconciliation retries converge drift or records a terminal failure.

### Sprint 2: Zero-Trust Service Security

Objective: remove development trust paths from the production boundary.

Exit criteria:

- Shared bearer token is dev-only.
- Service-to-service identity uses mTLS or platform workload identity.
- OIDC/JWKS is mandatory for production external callers.
- Secrets resolve from a managed provider.
- KMS-backed encryption and rotation are documented and tested.

### Sprint 3: Production Platform

Objective: deploy the full chassis through hardened, repeatable IaC.

Exit criteria:

- Helm or equivalent manifests cover broker, control plane, audit, metering,
  OPA, and portal.
- Workloads define resource requests, limits, pod security, service accounts,
  network policies, health probes, PDBs, and autoscaling.
- Terraform provisions IAM, KMS, private networking, data stores, ingress, DNS,
  WAF, logs, backups, and restore paths.
- A multi-AZ deployment survives an AZ loss.

### Sprint 4: Observability And Operations

Objective: make the platform operable by an enterprise SRE team.

Exit criteria:

- Metrics, traces, and structured logs are emitted by all services.
- SLOs exist for availability, policy latency, provision latency, and success
  rate.
- Alerts route to on-call.
- Load tests document capacity and scaling limits.
- Per-service runbooks and game-day exercises are complete.

### Sprint 5: Authorization Evidence

Objective: turn the SSP scaffolding into an assessed package.

Exit criteria:

- FIPS 199 categorization complete.
- SSP, POA&M, boundary diagram, control evidence, incident plan, and continuous
  monitoring artifacts are assessor-ready.
- 3PAO readiness review has been completed.
- Pilot boundary receives an authorization decision or documented remediation
  plan.
