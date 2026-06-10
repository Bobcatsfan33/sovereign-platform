"""Tests for the WS1 pilot harness orchestration (scripts/ws1_pilot.py).

The live run needs real infra; here we exercise the gate logic with a fake
broker so the harness itself is trustworthy before it is pointed at a cloud.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

_NO_SLEEP: dict[str, Any] = {"sleep": lambda _s: None}


def _load() -> ModuleType:
    path = ROOT / "scripts" / "ws1_pilot.py"
    spec = importlib.util.spec_from_file_location("ws1_pilot", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ws1_pilot"] = module
    spec.loader.exec_module(module)
    return module


class FakeBroker:
    def __init__(self, *, provision_op: str = "succeeded", reconcile_action: str = "reconciled") -> None:
        self._op_id = 0
        self._state = "provisioning"
        self._provision_op = provision_op
        self._reconcile_action = reconcile_action
        self._gone = False

    def provision(self, instance_id: str, body: dict[str, Any]) -> int:
        self._op_id = 1
        self._state = self._provision_op
        return 201

    def update(self, instance_id: str, body: dict[str, Any]) -> int:
        self._op_id += 1
        self._state = "succeeded"
        return 200

    def deprovision(self, instance_id: str) -> int:
        self._gone = True
        return 200

    def last_operation(self, instance_id: str) -> dict[str, Any]:
        if self._gone:
            return {"state": "gone", "operation": "gone"}
        return {
            "state": "succeeded",
            "operation": self._state,
            "operation_id": f"op-{self._op_id}",
            "applied_version": 1,
        }

    def reconcile(self, instance_id: str) -> dict[str, Any]:
        return {"results": [{"action": self._reconcile_action}]}


class FakeAudit:
    def __init__(self, actions: list[str]) -> None:
        self._actions = actions

    def actions_for(self, instance_id: str) -> list[str]:
        return self._actions


def _cfg(mod: ModuleType, **kw: Any) -> Any:
    return mod.PilotConfig(
        instance_id="i", service_id="sovereign-data-terraform", plan_id="standard", **kw
    )


def test_happy_path_passes() -> None:
    mod = _load()
    results = mod.run_pilot(FakeBroker(), None, _cfg(mod), **_NO_SLEEP)
    assert mod.report(results) is True
    names = {r.name: r for r in results}
    assert names["provision"].ok and names["update"].ok and names["deprovision"].ok
    # No drift cmds / audit url -> those phases skip but don't fail.
    assert names["drift_real"].skipped and names["evidence"].skipped


def test_failed_provision_is_no_go() -> None:
    mod = _load()
    results = mod.run_pilot(FakeBroker(provision_op="failed"), None, _cfg(mod), **_NO_SLEEP)
    assert mod.report(results) is False
    assert next(r for r in results if r.name == "provision").ok is False


def test_drift_real_requires_reconciled() -> None:
    mod = _load()
    cfg = _cfg(mod, drift_edit_cmd="true")
    assert mod.phase_drift_real(FakeBroker(reconcile_action="reconciled"), cfg).ok is True
    assert mod.phase_drift_real(FakeBroker(reconcile_action="in-sync"), cfg).ok is False


def test_drift_unknown_rejects_false_positive() -> None:
    mod = _load()
    cfg = _cfg(mod, drift_block_cmd="true", drift_unblock_cmd="true")
    # Unreachable backend must report unknown, not drift.
    assert mod.phase_drift_unknown(FakeBroker(reconcile_action="unknown"), cfg).ok is True
    # A "reconciled" on an unreachable backend would be a false positive -> fail.
    assert mod.phase_drift_unknown(FakeBroker(reconcile_action="reconciled"), cfg).ok is False


def test_evidence_requires_lifecycle_audit_events() -> None:
    mod = _load()
    cfg = _cfg(mod)
    good = FakeAudit(["instance.provisioned", "instance.updated", "instance.deprovisioned"])
    assert mod.phase_evidence(good, cfg).ok is True
    assert mod.phase_evidence(FakeAudit(["instance.provisioned"]), cfg).ok is False
