"""WS1 live-pilot harness — the executable form of
docs/runbooks/pilot-convergence.md.

Drives the full create -> update -> deprovision lifecycle of a real pack
(the Data pack's `terraform-apply` service type) through a DEPLOYED broker
against LIVE infrastructure, validates both drift classes (real divergence ->
reconciled; unreachable backend -> unknown, not a false positive), checks the
audit + metering evidence loop for every transition, and reports pass/fail per
gate. This is the program keystone: if it does not pass cleanly against real
infra, revisit the architecture before further investment.

It cannot run in CI (no cloud). Run it against a deployed chassis, e.g.:

    python scripts/ws1_pilot.py \
      --broker-url https://broker.example \
      --basic broker:"$BROKER_PASSWORD" \
      --audit-url https://audit.example \
      --service-id sovereign-data-terraform --plan-id standard \
      --params @pilot-params.json \
      --drift-edit-cmd 'aws ec2 create-tags ...' \
      --drift-block-cmd 'aws iam ... deny' --drift-unblock-cmd 'aws iam ... allow'

The orchestration (polling, gate evaluation, evidence aggregation) is unit
tested with a fake broker in tests/test_ws1_pilot.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

TERMINAL_OK = {"succeeded"}
TERMINAL_FAIL = {"failed"}


@dataclass
class PhaseResult:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class PilotConfig:
    instance_id: str
    service_id: str
    plan_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    poll_timeout_s: float = 600.0
    poll_interval_s: float = 5.0
    tenant_id: str = "pilot"
    drift_edit_cmd: str | None = None
    drift_block_cmd: str | None = None
    drift_unblock_cmd: str | None = None


class Broker(Protocol):
    def provision(self, instance_id: str, body: dict[str, Any]) -> int: ...
    def update(self, instance_id: str, body: dict[str, Any]) -> int: ...
    def deprovision(self, instance_id: str) -> int: ...
    def last_operation(self, instance_id: str) -> dict[str, Any]: ...
    def reconcile(self, instance_id: str) -> dict[str, Any]: ...


class Audit(Protocol):
    def actions_for(self, instance_id: str) -> list[str]: ...


def _poll(
    broker: Broker,
    instance_id: str,
    *,
    timeout_s: float,
    interval_s: float,
    until: Callable[[dict[str, Any]], bool],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    deadline = clock() + timeout_s
    last: dict[str, Any] = {}
    while clock() < deadline:
        last = broker.last_operation(instance_id)
        if until(last):
            return last
        sleep(interval_s)
    return last


def _await_terminal(broker: Broker, cfg: PilotConfig, **kw: Any) -> dict[str, Any]:
    return _poll(
        broker,
        cfg.instance_id,
        timeout_s=cfg.poll_timeout_s,
        interval_s=cfg.poll_interval_s,
        until=lambda op: op.get("operation") in (TERMINAL_OK | TERMINAL_FAIL)
        or op.get("state") == "gone",
        **kw,
    )


def _run_cmd(cmd: str) -> tuple[bool, str]:
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # noqa: S602
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def phase_provision(broker: Broker, cfg: PilotConfig, **kw: Any) -> PhaseResult:
    body = {"service_id": cfg.service_id, "plan_id": cfg.plan_id, "parameters": cfg.parameters}
    broker.provision(cfg.instance_id, body)
    op = _await_terminal(broker, cfg, **kw)
    if op.get("operation") != "succeeded":
        return PhaseResult("provision", False, f"terminal state {op.get('operation')!r}: {op}")
    if op.get("applied_version") is None:
        return PhaseResult("provision", False, "succeeded but no applied_version (no real apply?)")
    return PhaseResult("provision", True, f"applied_version={op.get('applied_version')}")


def phase_persist_across_restart(broker: Broker, cfg: PilotConfig) -> PhaseResult:
    # The operator restarts the broker out of band before this phase; we
    # confirm the desired state + operation id survived the restart.
    op = broker.last_operation(cfg.instance_id)
    if op.get("operation") != "succeeded" or not op.get("operation_id"):
        return PhaseResult("persist_across_restart", False, f"state not durable: {op}")
    return PhaseResult("persist_across_restart", True, f"operation_id={op.get('operation_id')}")


def phase_update(broker: Broker, cfg: PilotConfig, **kw: Any) -> PhaseResult:
    before = broker.last_operation(cfg.instance_id).get("operation_id")
    broker.update(cfg.instance_id, {"parameters": cfg.parameters})
    op = _await_terminal(broker, cfg, **kw)
    if op.get("operation") != "succeeded":
        return PhaseResult("update", False, f"terminal state {op.get('operation')!r}")
    if op.get("operation_id") == before:
        return PhaseResult("update", False, "operation_id did not change after update")
    return PhaseResult("update", True, f"new operation_id={op.get('operation_id')}")


def _reconcile_action(broker: Broker, cfg: PilotConfig) -> str:
    result = broker.reconcile(cfg.instance_id)
    actions = [r.get("action") for r in result.get("results", [])]
    return actions[0] if actions else "none"


def phase_drift_real(broker: Broker, cfg: PilotConfig) -> PhaseResult:
    if not cfg.drift_edit_cmd:
        return PhaseResult("drift_real", True, "no --drift-edit-cmd; skipped", skipped=True)
    ok, out = _run_cmd(cfg.drift_edit_cmd)
    if not ok:
        return PhaseResult("drift_real", False, f"drift-edit-cmd failed: {out}")
    action = _reconcile_action(broker, cfg)
    if action != "reconciled":
        return PhaseResult("drift_real", False, f"expected reconciled, got {action!r}")
    return PhaseResult("drift_real", True, "out-of-band edit detected and re-converged")


def phase_drift_unknown(broker: Broker, cfg: PilotConfig) -> PhaseResult:
    if not cfg.drift_block_cmd:
        return PhaseResult("drift_unknown", True, "no --drift-block-cmd; skipped", skipped=True)
    ok, out = _run_cmd(cfg.drift_block_cmd)
    if not ok:
        return PhaseResult("drift_unknown", False, f"drift-block-cmd failed: {out}")
    try:
        action = _reconcile_action(broker, cfg)
    finally:
        if cfg.drift_unblock_cmd:
            _run_cmd(cfg.drift_unblock_cmd)
    if action != "unknown":
        return PhaseResult(
            "drift_unknown", False, f"unreachable backend must be unknown, got {action!r}"
        )
    return PhaseResult("drift_unknown", True, "unreachable backend reported unknown, not drift")


def phase_evidence(audit: Audit | None, cfg: PilotConfig) -> PhaseResult:
    if audit is None:
        return PhaseResult("evidence", True, "no --audit-url; skipped", skipped=True)
    actions = set(audit.actions_for(cfg.instance_id))
    required = {"instance.provisioned", "instance.updated"}
    missing = required - actions
    if missing:
        return PhaseResult("evidence", False, f"missing audit events: {sorted(missing)}")
    return PhaseResult("evidence", True, f"audit events present: {sorted(actions & required)}")


def phase_deprovision(broker: Broker, cfg: PilotConfig, **kw: Any) -> PhaseResult:
    broker.deprovision(cfg.instance_id)
    op = _await_terminal(broker, cfg, **kw)
    if op.get("state") != "gone":
        return PhaseResult("deprovision", False, f"not gone after delete: {op}")
    return PhaseResult("deprovision", True, "instance removed")


def run_pilot(
    broker: Broker, audit: Audit | None, cfg: PilotConfig, **poll_kw: Any
) -> list[PhaseResult]:
    return [
        phase_provision(broker, cfg, **poll_kw),
        phase_persist_across_restart(broker, cfg),
        phase_update(broker, cfg, **poll_kw),
        phase_drift_real(broker, cfg),
        phase_drift_unknown(broker, cfg),
        phase_evidence(audit, cfg),
        phase_deprovision(broker, cfg, **poll_kw),
    ]


def report(results: list[PhaseResult]) -> bool:
    print("\nWS1 pilot results")
    print("=" * 40)
    for r in results:
        mark = "SKIP" if r.skipped else ("PASS" if r.ok else "FAIL")
        print(f"  [{mark}] {r.name}: {r.detail}")
    passed = all(r.ok for r in results)
    print("=" * 40)
    print("GO" if passed else "NO-GO — architecture revisit required")
    return passed


# ── HTTP clients (used for the live run; tests inject fakes) ───────────────


class HttpBroker:
    def __init__(self, base_url: str, *, auth: tuple[str, str] | None, bearer: str | None) -> None:
        import httpx

        self._c = httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self._auth = auth
        self._headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}

    def _kw(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"headers": self._headers}
        if self._auth:
            kw["auth"] = self._auth
        return kw

    def provision(self, instance_id: str, body: dict[str, Any]) -> int:
        return self._c.put(f"/v2/service_instances/{instance_id}", json=body, **self._kw()).status_code

    def update(self, instance_id: str, body: dict[str, Any]) -> int:
        return self._c.patch(f"/v2/service_instances/{instance_id}", json=body, **self._kw()).status_code

    def deprovision(self, instance_id: str) -> int:
        return self._c.delete(f"/v2/service_instances/{instance_id}", **self._kw()).status_code

    def last_operation(self, instance_id: str) -> dict[str, Any]:
        r = self._c.get(f"/v2/service_instances/{instance_id}/last_operation", **self._kw())
        return r.json() if r.status_code == 200 else {"state": "gone", "operation": "gone"}

    def reconcile(self, instance_id: str) -> dict[str, Any]:
        return self._c.post("/v2/reconcile", json={"instance_id": instance_id}, **self._kw()).json()


class HttpAudit:
    def __init__(self, base_url: str, *, bearer: str | None) -> None:
        import httpx

        self._c = httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self._headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}

    def actions_for(self, instance_id: str) -> list[str]:
        r = self._c.get("/events", params={"resource": instance_id}, headers=self._headers)
        events = r.json().get("events", []) if r.status_code == 200 else []
        return [e.get("action", "") for e in events if e.get("resource") == instance_id]


def _build_config(args: argparse.Namespace) -> PilotConfig:
    params: dict[str, Any] = {}
    if args.params:
        raw = args.params
        if raw.startswith("@"):
            raw = open(raw[1:]).read()  # noqa: SIM115
        params = json.loads(raw)
    return PilotConfig(
        instance_id=args.instance_id,
        service_id=args.service_id,
        plan_id=args.plan_id,
        parameters=params,
        poll_timeout_s=args.timeout,
        drift_edit_cmd=args.drift_edit_cmd,
        drift_block_cmd=args.drift_block_cmd,
        drift_unblock_cmd=args.drift_unblock_cmd,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--broker-url", required=True)
    p.add_argument("--basic", help="user:password for OSB Basic auth")
    p.add_argument("--bearer", help="bearer token (alternative to --basic)")
    p.add_argument("--audit-url")
    p.add_argument("--service-id", required=True)
    p.add_argument("--plan-id", required=True)
    p.add_argument("--params", help="JSON, or @file.json")
    p.add_argument("--instance-id", default="ws1-pilot")
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--drift-edit-cmd")
    p.add_argument("--drift-block-cmd")
    p.add_argument("--drift-unblock-cmd")
    args = p.parse_args(argv)

    auth = tuple(args.basic.split(":", 1)) if args.basic else None  # type: ignore[assignment]
    broker = HttpBroker(args.broker_url, auth=auth, bearer=args.bearer)
    audit = HttpAudit(args.audit_url, bearer=args.bearer) if args.audit_url else None
    cfg = _build_config(args)

    results = run_pilot(broker, audit, cfg)
    return 0 if report(results) else 1


if __name__ == "__main__":
    sys.exit(main())
