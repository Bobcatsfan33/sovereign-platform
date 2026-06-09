# Runbook: WS1 Pilot Convergence (live apply/reconcile proof)

The keystone go/no-go. Proves the renderer→executor→reconciler path against
**real** infrastructure, not test doubles. Run against a throwaway AWS account
and a real managed Kubernetes cluster, provisioned fresh so the test is
repeatable and teardown is verified.

Pick the riskiest pilot: the **Data pack `terraform-apply`** service type
(exercises init/plan/apply/state/outputs), not a config-only pack.

## Preconditions

- Disposable AWS account; `terraform`, `kubectl`, `aws` on PATH for the
  executor pods; per-service IAM roles from WS2 IaC applied.
- Chassis deployed (broker, control-plane, audit-service, metering-service),
  `ENV` not in the dev allowlist, managed secrets wired, mesh in permissive.
- A scratch S3 state backend + DynamoDB lock table for the pilot module.

## Procedure

1. **Create.** `PUT /v2/service_instances/{id}` for the Data terraform-apply
   plan. Poll `last_operation` until `succeeded`. Confirm:
   - the executor ran real `terraform init` + `apply` (no patched shell-out);
   - `apply_outputs` carries the real Terraform outputs;
   - the resource exists in AWS (verify out-of-band).
2. **Persist across restart.** Restart the broker pod. Re-read the instance;
   desired state, `operation_id`, and OSB `last_operation` must reflect the
   real apply, not a re-render.
3. **Update.** `PATCH` the instance with a changed parameter. Confirm a new
   apply converges and a new `operation_id`/`succeeded` state is recorded.
4. **Drift — real divergence.** Hand-edit the provisioned resource out of band
   (e.g. change a tag in the AWS console). Run the reconcile/diff path; confirm
   it reports **DRIFTED** (not unknown), then re-converges and records it.
5. **Drift — unreachable backend.** Block the state backend (revoke the role or
   network). Confirm the diff reports **unknown**, NOT drift (no false
   positive). Restore access.
6. **Terminal failure.** Provision an intentionally invalid module. Confirm
   `last_operation` reaches `failed` with operator-readable evidence, and the
   instance records the failed step kind.
7. **Deprovision.** `DELETE` the instance; confirm real `terraform destroy`,
   then verify the resource is gone in AWS and the table row is removed.

## Evidence loop (must hold for every transition above, incl. failures)

- An **audit event** is emitted for each lifecycle transition (hash-chained).
- A **metering record** is written for each transition.
- The in-process evidence-completeness e2e (`tests/test_lifecycle_evidence.py`)
  asserts this against the real state machine; this runbook confirms it holds
  against live executors too.

## Exit gate

Create/update/deprovision complete against live infra with no patched
shell-out; both drift classes behave correctly; reconcile converges or records
a terminal failure with evidence; audit + metering are complete. If this cannot
be made to work cleanly, **revisit the architecture before further investment.**

## Teardown

Destroy the pilot module, delete the scratch state backend + lock table, and
close/scrub the throwaway account. Teardown is part of the proof — a pilot you
can't cleanly remove isn't repeatable.
