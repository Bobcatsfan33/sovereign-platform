"""Tests for the deployment executor subsystem (Step 0.2)."""

from __future__ import annotations

import pytest
from sovereign.executors import (
    BaseExecutor,
    ExecResult,
    KubernetesExecutor,
    NoopExecutor,
    apply_manifest,
    register_default_executors,
    register_executor,
)
from sovereign.executors import registry as executor_registry
from sovereign.executors import shell as shell_mod
from sovereign.renderers.artifact import DeploymentStep


def test_executor_requires_kind() -> None:
    with pytest.raises(TypeError, match="kind"):

        class _Bad(BaseExecutor):
            async def execute(self, step):  # type: ignore[no-untyped-def]
                return ExecResult(ok=True)


def test_register_and_get() -> None:
    executor_registry.clear()
    ex = NoopExecutor()
    register_executor(ex)
    assert "envoy-snapshot" in executor_registry.kinds()
    assert executor_registry.get("envoy-snapshot") is ex


def test_register_default_executors() -> None:
    executor_registry.clear()
    register_default_executors()
    assert set(executor_registry.kinds()) == {
        "envoy-snapshot",
        "helm-upgrade",
        "k8s-apply",
        "terraform-apply",
        "webhook",
    }


async def test_noop_executor_acknowledges() -> None:
    r = await NoopExecutor().execute(DeploymentStep(kind="envoy-snapshot", target="i1"))
    assert r.ok
    assert "i1" in r.detail


async def test_apply_manifest_runs_all_steps() -> None:
    executor_registry.clear()
    register_executor(NoopExecutor())

    class _Echo(BaseExecutor):
        kind = "echo"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True, detail=step.target)

    register_executor(_Echo())
    manifest = [
        DeploymentStep(kind="echo", target="a"),
        DeploymentStep(kind="envoy-snapshot", target="b"),
    ]
    result = await apply_manifest(manifest)
    assert result.ok
    assert len(result.applied_steps) == 2


async def test_apply_manifest_unknown_kind_fails_loudly() -> None:
    executor_registry.clear()
    result = await apply_manifest([DeploymentStep(kind="nonexistent", target="x")])
    assert not result.ok
    assert result.failed_step is not None
    assert "no executor registered" in result.detail


async def test_apply_manifest_stops_at_first_failure() -> None:
    executor_registry.clear()

    class _Fail(BaseExecutor):
        kind = "boom"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=False, detail="kaboom")

    register_executor(NoopExecutor())
    register_executor(_Fail())
    manifest = [
        DeploymentStep(kind="envoy-snapshot", target="ok"),
        DeploymentStep(kind="boom", target="bad"),
        DeploymentStep(kind="envoy-snapshot", target="never"),
    ]
    result = await apply_manifest(manifest)
    assert not result.ok
    assert len(result.applied_steps) == 1  # only the first ran
    assert result.failed_step is not None
    assert result.failed_step.kind == "boom"


async def test_kubernetes_executor_missing_cli(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: None)
    r = await KubernetesExecutor().execute(
        DeploymentStep(kind="k8s-apply", target="ns", payload={"manifest_path": "/x.yaml"})
    )
    assert not r.ok
    assert "kubectl not found" in r.detail


async def test_kubernetes_executor_applies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: "/usr/bin/kubectl")
    calls: list[list[str]] = []

    def fake_run(cmd, *, timeout=120.0):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return 0, "deployment configured", ""

    monkeypatch.setattr(shell_mod, "_run", fake_run)
    r = await KubernetesExecutor().execute(
        DeploymentStep(kind="k8s-apply", target="prod", payload={"manifest_path": "/tmp/d.yaml"})
    )
    assert r.ok
    assert r.outputs["namespace"] == "prod"
    assert calls[0][:3] == ["kubectl", "apply", "-n"]


async def test_kubernetes_executor_requires_manifest_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: "/usr/bin/kubectl")
    r = await KubernetesExecutor().execute(DeploymentStep(kind="k8s-apply", target="ns"))
    assert not r.ok
    assert "manifest_path" in r.detail


# ── Drift detection: executor.diff() + diff_manifest (ADR-0004) ────────


async def test_base_diff_default_reports_in_sync() -> None:
    from sovereign.executors import NoopExecutor

    d = await NoopExecutor().diff(DeploymentStep(kind="envoy-snapshot", target="i1"))
    assert d.checked is True
    assert d.drifted is False


async def test_kubernetes_diff_in_sync(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: "/usr/bin/kubectl")
    # kubectl diff exit 0 == no difference
    monkeypatch.setattr(shell_mod, "_run", lambda cmd, *, timeout=120.0: (0, "", ""))
    d = await KubernetesExecutor().diff(
        DeploymentStep(kind="k8s-apply", target="prod", payload={"manifest_path": "/x.yaml"})
    )
    assert d.checked is True
    assert d.drifted is False


async def test_kubernetes_diff_detects_drift(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: "/usr/bin/kubectl")
    # kubectl diff exit 1 == difference present
    monkeypatch.setattr(shell_mod, "_run", lambda cmd, *, timeout=120.0: (1, "- old\n+ new", ""))
    d = await KubernetesExecutor().diff(
        DeploymentStep(kind="k8s-apply", target="prod", payload={"manifest_path": "/x.yaml"})
    )
    assert d.checked is True
    assert d.drifted is True


async def test_kubernetes_diff_error_is_unchecked(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: "/usr/bin/kubectl")
    # exit >1 == error -> fail-safe unchecked (NOT drifted)
    monkeypatch.setattr(shell_mod, "_run", lambda cmd, *, timeout=120.0: (3, "", "boom"))
    d = await KubernetesExecutor().diff(
        DeploymentStep(kind="k8s-apply", target="prod", payload={"manifest_path": "/x.yaml"})
    )
    assert d.checked is False
    assert d.drifted is False


async def test_kubernetes_diff_missing_cli_is_unchecked(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: None)
    d = await KubernetesExecutor().diff(
        DeploymentStep(kind="k8s-apply", target="prod", payload={"manifest_path": "/x.yaml"})
    )
    assert d.checked is False


async def test_terraform_diff_detects_drift(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sovereign.executors.shell import TerraformExecutor

    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: "/usr/bin/terraform")
    # init returns 0; plan -detailed-exitcode returns 2 (changes present)
    calls: list[list[str]] = []

    def fake_run(cmd, *, timeout=120.0):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if "init" in cmd:
            return 0, "", ""
        return 2, "Plan: 1 to add", ""

    monkeypatch.setattr(shell_mod, "_run", fake_run)
    d = await TerraformExecutor().diff(
        DeploymentStep(kind="terraform-apply", target="db", payload={"module_dir": "/m"})
    )
    assert d.checked is True
    assert d.drifted is True
    assert any("plan" in c for c in calls)


async def test_terraform_diff_in_sync(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sovereign.executors.shell import TerraformExecutor

    monkeypatch.setattr(shell_mod.shutil, "which", lambda _b: "/usr/bin/terraform")
    monkeypatch.setattr(shell_mod, "_run", lambda cmd, *, timeout=120.0: (0, "No changes", ""))
    d = await TerraformExecutor().diff(
        DeploymentStep(kind="terraform-apply", target="db", payload={"module_dir": "/m"})
    )
    assert d.checked is True
    assert d.drifted is False


async def test_diff_manifest_aggregates_drift() -> None:
    from sovereign.executors import diff_manifest, register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, DiffResult, ExecResult

    ex_registry.clear()

    class _InSync(BaseExecutor):
        kind = "insync"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True)

        async def diff(self, step):  # type: ignore[no-untyped-def]
            return DiffResult(checked=True, drifted=False)

    class _Drift(BaseExecutor):
        kind = "drift"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True)

        async def diff(self, step):  # type: ignore[no-untyped-def]
            return DiffResult(checked=True, drifted=True, detail="changed")

    register_executor(_InSync())
    register_executor(_Drift())
    md = await diff_manifest(
        [DeploymentStep(kind="insync", target="a"), DeploymentStep(kind="drift", target="b")]
    )
    assert md.drifted is True
    assert md.unknown is False
    assert len(md.details) == 2


async def test_diff_manifest_unknown_when_no_executor() -> None:
    from sovereign.executors import diff_manifest
    from sovereign.executors import registry as ex_registry

    ex_registry.clear()
    md = await diff_manifest([DeploymentStep(kind="no-such-kind", target="x")])
    assert md.drifted is False  # fail-safe: unchecked is not drift
    assert md.unknown is True


async def test_diff_manifest_unchecked_does_not_count_as_drift() -> None:
    from sovereign.executors import diff_manifest, register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, DiffResult, ExecResult

    ex_registry.clear()

    class _Unreachable(BaseExecutor):
        kind = "unreachable"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True)

        async def diff(self, step):  # type: ignore[no-untyped-def]
            return DiffResult(checked=False, detail="backend down")

    register_executor(_Unreachable())
    md = await diff_manifest([DeploymentStep(kind="unreachable", target="x")])
    assert md.drifted is False
    assert md.unknown is True
