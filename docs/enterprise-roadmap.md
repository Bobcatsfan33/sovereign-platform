# Sovereign Platform — Enterprise Roadmap (re-baselined)

> **Status of this document.** This is a re-baseline of an earlier roadmap whose
> premises no longer match the repository. It was written against `main @ 7d3c0bd`
> and assumed the enterprise sprint work lived only on branches and that the
> provisioning path never executed a deployment manifest. **Both assumptions are
> false on the current `main`.** This document records the verified state and the
> genuinely remaining work. Verified on `main @ a1e83f9` (and forward).

## Part 1 — Merge plan: ALREADY DONE (no-op)

The earlier plan called for integrating a linear stack of
`codex/enterprise-sprint-0 … 14` branches onto `main`. That integration has
already happened:

- `main` contains the merge commit **`d603f75` "Enterprise and ATO hardening
  through Sprint 14"** on its first-parent history.
- Every named sprint SHA (`dfffa87`, `35dfbcd`, `ab84c10`, `8d78a2c`, `82699e5`,
  `3d60957`, `d4318a8`, `b0349c4`, … `4394a69`) is an **ancestor of `main`**.
- `git rev-list --count main..codex/enterprise-sprint-14-ssp-accuracy` = **0**.

Therefore the only Part-1 actions with any effect are housekeeping:

1. **Delete the merged `codex/*` branches.** Each is a verified ancestor of
   `main` (`git merge-base --is-ancestor <branch> main` succeeds), so deletion
   loses no history — the commits live on `main`.
2. **Ignore the `feat/*` branches** — already on `main` (PRs #1–#13).
3. **Establish versioning.** Tag a first release and keep a CHANGELOG.

The merge-time guardrails from the original plan remain accurate and are now
tracked as **Epic 2** (insecure `dev-token` / `minioadmin` defaults still exist;
`broker_trust_basic_auth` still has a bypass path).

## Part 2 — Epic 1, re-scoped to the actual gap

The original Epic 1 said *"the broker renders desired config and marks the
instance succeeded — it never executes the deployment manifest."* **This is no
longer true.** Execution is wired, one hop downstream of where the original
roadmap looked:

```
broker._finalize_provision()
  → render()                       (POST control-plane /render)
      → renderer.render()
      → renderer.validate()
      → renderer.apply()           ← apps/control-plane/app/main.py:135
          → apply_manifest(manifest) → executor.execute(step)   (for every pack)
          → EnvoyRenderer.apply()  → s3.put_object(...)         (chassis LB)
  → _mark_operation_succeeded()    only after apply returns ok
```

A failing apply already returns a 503 from the control plane, which the broker
turns into a terminal OSB `failed` state with the failed step kind and an audit
event (`_mark_operation_failed`). Re-apply is idempotent (executors converge).

So ADR-0003's 7-step workflow is satisfied **except step 6's detection half**:

| ADR-0003 step | Status |
| --- | --- |
| 1. Persist desired state | ✅ |
| 2. Render artifact | ✅ |
| 3. Validate artifact | ✅ |
| 4. Execute every step via executor registry | ✅ (via control-plane apply) |
| 5. Persist operation state + outputs | ✅ |
| 6. Reconcile until actual == desired | ⚠️ **correction yes, detection no** |
| 7. Metering + audit evidence | ✅ |

**The remaining Epic-1 work (this PR series):**

- **True drift *detection*.** `_needs_reconcile()` only inspects status fields —
  it never reads actual backend state. Add a real `diff()` that queries the
  backend (`kubectl diff`, `terraform plan -detailed-exitcode`) and sets
  `DriftStatus.drifted` from a real comparison.
- **Periodic reconciler.** Reconcile only fires via the manual `POST /v2/reconcile`.
  Add a scheduled background trigger that refreshes drift and re-converges
  drifted instances, idempotently and rate-limited.
- **ADR-0004** recording the canonical apply path (control-plane
  `renderer.apply` → `apply_manifest`) so the two apply mechanisms are no longer
  ambiguous, and the new drift path that mirrors it.

This is delivered in `feat/epic1-drift-reconcile`.

## Epics E2–E7 (forward work — unchanged premises, still valid)

These were assessed against the current code and remain accurate open work:

- **E2 — Zero-trust auth & secrets.** `dev_bearer_token` still defaults to
  `"dev-token"` (`settings.py`); the Basic-auth RBAC bypass path still exists
  behind `broker_trust_basic_auth`; mTLS is still a boolean field. Disqualifying
  for a shared-environment deploy until closed.
- **E3 — Production IaC, HA & DR.** Terraform is a thin skeleton; `production.yaml`
  is flat (no HPA/PDB/multi-AZ); no Helm chart.
- **E4 — Data durability & migrations.** No migration framework; emulators only;
  no backup/restore drill.
- **E5 — Observability depth.** `/metrics` helper exists (sprint 4); no tracing,
  SLOs, or alerting.
- **E6 — ATO track.** SSP/POA&M scaffolding exists; convert to an authorized
  package (long external lead time — start in parallel).
- **E7 — GA hardening & release discipline.** No releases yet; establish
  versioning, pen test, pilot tenant.

## Definition of done (whole program)

1. A tenant request provisions real, converged, **drift-detected-and-corrected**
   infrastructure. *(Epic 1 — execution ✅, detection in this PR series.)*
2. No shared secrets or auth bypass; inter-service mTLS. *(E2)*
3. Full stack via IaC, multi-AZ, tested backup/restore + DR. *(E3, E4)*
4. Golden-signal observability, SLOs, on-call. *(E5)*
5. ATO/P-ATO for the boundary + continuous monitoring. *(E6)*
6. Versioned releases, pen-tested, operator + tenant docs. *(E7)*
