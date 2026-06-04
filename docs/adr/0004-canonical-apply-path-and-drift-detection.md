# ADR 0004: Canonical Apply Path and Drift Detection

## Status

Accepted.

## Context

ADR-0003 specified a desired-state workflow whose step 4 ("execute every
deployment step through the executor registry") and step 6 ("reconcile actual
state until it matches desired state") were not both implemented. Two facts
about the current code created ambiguity for anyone trying to finish step 6:

1. **There are two apply mechanisms.**
   - `EnvoyRenderer.apply()` (`renderers/envoy.py`) — renderer-native; does the
     `s3-put` / `envoy-snapshot` work for the chassis load balancer directly.
   - `apply_manifest()` (`executors/dispatch.py`) — walks a
     `deployment_manifest` and runs each step through the executor registry
     (`k8s-apply` / `terraform-apply` / `helm-upgrade` / `webhook` / `envoy-snapshot`).

   Every **pack** renderer's `apply()` already delegates to `apply_manifest()`.
   Only the chassis `EnvoyRenderer` keeps a renderer-native apply.

2. **Apply runs in the control plane, not the broker.** The broker's
   `_finalize_provision()` calls `render()` which POSTs to control-plane
   `/render`, and that endpoint runs `renderer.render → validate → apply`. So
   execution is already wired — through the control plane — contrary to an
   earlier assumption that the broker must call the executor directly.

Drift *correction* exists (`POST /v2/reconcile` re-runs the same apply,
idempotently). Drift *detection* does not: `_needs_reconcile()` only inspects
persisted status fields and never reads actual backend state.

## Decision

### Canonical apply path

`renderer.apply()`, invoked by the control-plane `/render` endpoint, is the
single canonical apply path. `apply_manifest()` (the executor registry) is the
general implementation that path uses; `EnvoyRenderer.apply()` is the one
renderer that applies natively (its manifest's `s3-put`/`envoy-snapshot` kinds
are chassis-internal). The broker does **not** call executors directly — it
drives apply via the control plane. This keeps a single execution surface and a
single place (the control plane) that holds backend credentials/CLIs.

### Drift detection

Mirror the apply path for detection:

- Each `BaseExecutor` gains an optional `diff(step) -> DiffResult` that queries
  the backend for that step and reports whether actual matches desired
  (`kubectl diff`, `terraform plan -detailed-exitcode`, etc.). Executors that
  cannot meaningfully diff (noop/webhook) report `in_sync` (nothing to drift).
- `apply_manifest()` gains a sibling `diff_manifest(manifest) -> ManifestDiff`
  that walks the same steps and aggregates their diff results.
- The control plane exposes `POST /diff` (alongside `/render`) that runs
  `renderer.render → diff_manifest` and returns whether the instance has drifted.
- The broker's drift refresh calls control-plane `/diff` and sets
  `DriftStatus.drifted | in_sync` from the **real** comparison, replacing the
  status-only heuristic as the source of truth for "has this drifted."
- A periodic reconciler refreshes drift for managed instances and re-converges
  drifted ones, idempotently and bounded by the existing rate limiter.

Detection is **fail-safe, not fail-closed**: if a backend can't be reached for a
diff, the instance is left `unknown` (not forced to `drifted`) so a transient
backend blip doesn't trigger a reconcile storm. A real `drifted` result always
comes from a successful comparison that found a difference.

## Consequences

- Adding a new executor means optionally implementing `diff()`; the base default
  reports `in_sync` so existing executors keep working.
- The broker keeps no backend credentials — both apply and diff go through the
  control plane.
- `_needs_reconcile()` still triggers on lifecycle conditions (provisioning/
  failed/version-skew) **and** on a real `drifted` result.

## Exit Criteria

- An out-of-band change to a pilot resource is detected by a real backend diff
  and surfaces as `DriftStatus.drifted`.
- The periodic reconciler re-converges a drifted instance without manual action.
- A backend that cannot be diffed leaves the instance `unknown`, not `drifted`.
