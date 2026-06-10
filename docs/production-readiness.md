# Production-Readiness Plan

Basis: external infrastructure-engineering assessment of `0.5.0-alpha`. This
is the tracked, living version of that roadmap. Each workstream states the
gap, the engineering work, the exit gate, and the **current status** in this
repo. Status legend:

- **done** — implemented and covered by the green test gate.
- **partial** — substantive code landed; remainder noted.
- **live-gated** — code/runbook ready; the gate needs live infrastructure
  (cloud account, real cluster) this repo's CI cannot stand up.
- **external** — closed only by an outside party or a human decision (assessor,
  pen tester, authorizing official, owning team).

The dependency order is the assessment's: **WS1 is the keystone** — it governs
whether the downstream investment is justified.

---

## WS1 — Prove the apply/reconcile loop against reality

**Gap.** The renderer→executor→reconciler path is implemented and unit-tested,
but with mocked CLIs.

**Status: partial → live-gated.**
- The drift architecture is already fail-safe: `executors/dispatch.py`
  separates `unknown` (backend unreachable / missing CLI / no executor) from
  `drifted` (real divergence); `terraform plan -detailed-exitcode` and
  `kubectl diff` exit codes are mapped correctly. An unreachable backend
  reports **unknown**, never a false-positive drift. *(done)*
- **Evidence completeness** — every lifecycle transition, including failure
  paths, emits audit + metering — is verified by an in-process e2e that drives
  the real broker state machine + dispatch + executors against moto with a
  deterministic executor (no broker-boundary mocks). *(this plan series)*
- **Live pilot** (Data pack `terraform-apply` against a throwaway AWS account +
  real managed k8s, full create/update/deprovision unmocked, out-of-band drift
  reconciled) — see `docs/runbooks/pilot-convergence.md`. *(live-gated)*

**Exit gate.** One pack completes create/update/deprovision against live infra
with no patched shell-out; drift detected and reconciled; audit + metering
evidence complete.

## WS2 — Production substrate, HA, and DR

**Gap.** Skeleton Terraform; no KMS/IAM/NAT/WAF/DNS/backup modules; no multi-AZ
proof; thin workload governance.

**Status: partial → live-gated.**
- Hardened IaC modules (multi-AZ across 3 zones, tiered subnets, KMS with
  rotation, least-privilege per-service IAM, NAT/ingress) and production
  workload governance (HPA, resource requests/limits, tuned PDBs, ASG
  target-tracking + alarms) are authored as code. *(this plan series)*
- DynamoDB PITR + S3 versioning exist; `sovereign.backup` adds a tested
  restore drill (E4). *(done)*
- **AZ-loss game-day** with measured RTO/RPO, and a restore executed from
  backup — see `docs/runbooks/az-loss-gameday.md`. *(live-gated)*

**Exit gate.** Full chassis deploys through hardened multi-AZ IaC; induced AZ
failure survived with documented RTO/RPO; restore performed.

## WS3 — Observability and operability

**Gap.** Metrics + logs exist; no tracing across the provisioning path, no
SLOs, no on-call routing, no load tests.

**Status: partial → live-gated.**
- RED metrics, W3C trace propagation, and SLO recording + burn-rate alert
  rules landed in E5 (`metrics.py`, `tracing.py`, `observability.py`,
  `deploy/k8s/prometheus-rules.yaml`, `docs/slo.md`). *(done)*
- **Provisioning-path tracing** — broker → control-plane → executors carrying
  one trace — wired on the outbound call path. *(this plan series)*
- Per-service runbooks + game-day procedures for infra-loss and bad-policy
  rollout. *(this plan series — docs)*
- **Load test + published capacity** (k6 against the broker + policy path) —
  harness committed; the run needs a deployed target. *(live-gated)*

**Exit gate.** Metrics + traces + logs from every service; SLOs with on-call
alerts; documented capacity from real load tests; runbooks + game-day results.

## WS4 — Compliance and authorization

**Gap.** Authorization package is scaffolding; no FIPS-199 categorization, no
assessment, single framework, no crosswalks.

**Status: partial → external.**
- SSP control evidence is machine-validated (E6, `scripts/ssp_validate.py`):
  96 controls, all cited evidence resolves. *(done)*
- FIPS-199 categorization and a second-framework crosswalk (NIST 800-53 →
  a second baseline) are authored + validated. *(this plan series)*
- **Third-party readiness review + authorization decision.** *(external —
  start the documentation track now; long external lead time.)*

**Exit gate.** Assessor-ready package (categorization, SSP, evidence, IR,
conmon); third-party review; authorization decision or documented remediation.

## WS5 — Productization, API lifecycle, multi-cloud honesty

**Gap.** No API versioning/upgrade path; manual secret rotation; AWS-only
substrate despite a multi-cloud pack; no external pen test.

**Status: partial → external.**
- API versioning + a tested upgrade path (the payload schema-migration
  framework from E4 is the data half). *(this plan series)*
- Automated, tested secret rotation atop the managed-secrets provider (E2).
  *(this plan series)*
- **Multi-cloud honesty** — a capability matrix + a guard test asserting
  advertised providers match implemented backends, so the label can't outrun
  the capability. *(this plan series)*
- **Independent penetration test + disclosure process** (`SECURITY.md`).
  *(external — disclosure process is code/doc; the pen test is external.)*

**Exit gate.** Versioned API + tested upgrade; automated rotation; multi-cloud
claims matched by implementation or scope; clean external pen test + disclosure
process.

## WS6 — Ownership and support model

**Gap.** Effectively single-maintainer alpha; no support/patch/ownership model.

**Status: external (human decision).**
- `docs/governance.md` + `SECURITY.md` capture the release/deprecation policy,
  security-response SLA template, and escalation path. *(this plan series —
  the documents.)*
- **The build-vs-buy ownership decision** and the named owning team / vendor
  with real SLAs is a leadership decision this repo cannot make. *(external.)*

**Exit gate.** Named owner/vendor with defined SLAs, security-response
commitment, and a release/upgrade policy operations can rely on.

---

## Delivered in this program

Code/config/doc deliverables shipped against the workstreams (all merged, the
test gate green). The **live-gated** and **external** items above remain.

| WS | Delivered | PR |
|----|-----------|----|
| WS1 | Audit the sync provision-failure path (closed evidence gap) + lifecycle evidence e2e | #38 |
| WS3 | Trace propagation across the provisioning path (service-to-service + executor subprocess) | #39 |
| WS3 | Deep `/readyz` readiness gating traffic on dependency health | #43 |
| WS5 | Automatic secret rotation (TTL refetch + re-resolve) | #40 |
| WS5 | HashiCorp Vault secrets backend (cloud-agnostic substrate) | #41 |
| WS5 | API version negotiation + RFC 8594 deprecation/sunset | #42 |
| WS5 | Secret-rotation webhook (instant cutover) | #44 |
| WS4 | NIST 800-53 → ISO/IEC 27001 crosswalk, validated | #45 |
| WS2 | Horizontal pod autoscaling for backend services | #46 |
| WS2 | KMS key rotation + least-privilege per-service IAM | #47 |
| WS6 | `SECURITY.md` disclosure policy + `docs/governance.md` contract | #48 |

## What code cannot close

Per the assessment, the program's keystone (WS1 live pilot) and several exit
gates require a live cloud account, a real cluster, an external assessor, a
pen-test engagement, and a human ownership decision. Those are tracked here as
**live-gated** / **external** with the runbooks/harnesses that make them
executable — not marked done. The bottom line stands: fund the WS1 live pilot
first and let its result govern the rest.
