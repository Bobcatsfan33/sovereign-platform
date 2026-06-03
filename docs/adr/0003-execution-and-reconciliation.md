# ADR 0003: Execution And Reconciliation Model

## Status

Accepted for Sprint 0.

## Context

The broker currently validates requests, checks RBAC/quota/policy, persists
desired state, and asks the control plane to render artifacts. That proves the
API and policy spine, but enterprise customers expect a provisioning platform to
converge real resources and recover from drift.

The renderer and executor abstractions already exist. The next sprint must wire
them into an execution path and then evolve that path into a controller.

## Decision

Provisioning must become a desired-state workflow:

1. Persist desired state.
2. Render the artifact for the selected service type.
3. Validate the artifact.
4. Execute every deployment step through the executor registry.
5. Persist operation state and outputs.
6. Reconcile actual state until it matches desired state.
7. Emit metering and audit evidence.

The first implementation may run execution inline or through a background worker,
but it must use idempotent operation IDs and terminal OSB `last_operation`
states. A later controller must periodically detect drift and re-converge actual
state.

## Consequences

- A rendered artifact is not enough to mark an instance as succeeded.
- Every pack in the authorization boundary must implement render, validate,
  apply, teardown, and drift-check semantics.
- Failed apply operations must stop the manifest, record the failed step, emit an
  audit event, and expose a terminal failed state to OSB clients.
- The first pilot should choose one pack and prove end-to-end convergence before
  broadening the pack surface.

## Exit Criteria

- A provision request creates a real resource in the target environment.
- Re-running the same operation is idempotent.
- Failed execution returns a clear OSB failed state and audit trail.
- Drift can be detected and corrected for the pilot pack.
