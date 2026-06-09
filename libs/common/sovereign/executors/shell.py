"""CLI-backed executors for the standard deployment step kinds.

Real platforms apply K8s/Helm/Terraform via their CLIs; the chassis does
the same rather than vendoring heavy client libraries. Each executor
shells out through `_run`, which is a thin wrapper that tests patch to
avoid touching real clusters/clouds. A missing CLI is reported as a clean
ExecResult(ok=False) rather than an exception so a manifest referencing a
backend the host can't reach fails predictably.

NoopExecutor handles "nothing to orchestrate" kinds (e.g. the Envoy
renderer's `envoy-snapshot`, where hosts poll on a timer).
WebhookExecutor POSTs to a URL — the lightest possible integration hook.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import ClassVar

import httpx

from ..renderers.artifact import DeploymentStep
from ..tracing import subprocess_trace_env
from .base import BaseExecutor, DiffResult, ExecResult

logger = logging.getLogger("sovereign.executors.shell")


def _run(cmd: list[str], *, timeout: float = 120.0) -> tuple[int, str, str]:
    """Run a CLI command. Isolated so tests patch this single function.
    Returns (returncode, stdout, stderr). The current trace is injected as
    TRACEPARENT so the apply step is correlatable in the request's trace."""
    proc = subprocess.run(  # noqa: S603 — args are chassis-controlled, never raw user input
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, **subprocess_trace_env()},
    )
    return proc.returncode, proc.stdout, proc.stderr


def _cli_or_error(binary: str) -> ExecResult | None:
    if shutil.which(binary) is None:
        return ExecResult(ok=False, detail=f"{binary} not found on PATH")
    return None


class NoopExecutor(BaseExecutor):
    """Records a step that needs no active orchestration (poll-based)."""

    kind: ClassVar[str] = "envoy-snapshot"

    async def execute(self, step: DeploymentStep) -> ExecResult:
        logger.info("noop executor: %s target=%s", step.kind, step.target)
        return ExecResult(ok=True, detail=f"acknowledged {step.kind} for {step.target}")


class KubernetesExecutor(BaseExecutor):
    """`kubectl apply` the manifest in step.payload['manifest_path'] (or
    pipe step.payload['manifest'] via stdin). target is the namespace."""

    kind: ClassVar[str] = "k8s-apply"

    async def execute(self, step: DeploymentStep) -> ExecResult:
        if (err := _cli_or_error("kubectl")) is not None:
            return err
        ns = step.target or "default"
        path = step.payload.get("manifest_path")
        if not path:
            return ExecResult(ok=False, detail="k8s-apply requires payload.manifest_path")
        rc, out, errtxt = _run(["kubectl", "apply", "-n", ns, "-f", path])
        if rc != 0:
            return ExecResult(ok=False, detail=f"kubectl apply failed: {errtxt.strip() or out.strip()}")
        return ExecResult(ok=True, detail=f"applied to namespace {ns}", outputs={"namespace": ns})

    async def diff(self, step: DeploymentStep) -> DiffResult:
        """`kubectl diff` exit codes: 0 = no diff, 1 = diff present, >1 =
        error. Map 0→in-sync, 1→drifted, anything else (incl. missing CLI)
        →unchecked (fail-safe)."""
        if shutil.which("kubectl") is None:
            return DiffResult(checked=False, detail="kubectl not found on PATH")
        ns = step.target or "default"
        path = step.payload.get("manifest_path")
        if not path:
            return DiffResult(checked=False, detail="k8s diff requires payload.manifest_path")
        rc, _out, errtxt = _run(["kubectl", "diff", "-n", ns, "-f", path])
        if rc == 0:
            return DiffResult(checked=True, drifted=False, detail=f"{ns}: in sync")
        if rc == 1:
            return DiffResult(checked=True, drifted=True, detail=f"{ns}: drift detected")
        return DiffResult(checked=False, detail=f"kubectl diff error: {errtxt.strip()}")


class HelmExecutor(BaseExecutor):
    """`helm upgrade --install`. target is the release name; payload
    carries chart, namespace, and optional values_file."""

    kind: ClassVar[str] = "helm-upgrade"

    async def execute(self, step: DeploymentStep) -> ExecResult:
        if (err := _cli_or_error("helm")) is not None:
            return err
        release = step.target
        chart = step.payload.get("chart")
        if not release or not chart:
            return ExecResult(ok=False, detail="helm-upgrade requires target (release) and payload.chart")
        cmd = ["helm", "upgrade", "--install", release, chart]
        if ns := step.payload.get("namespace"):
            cmd += ["--namespace", ns, "--create-namespace"]
        if values := step.payload.get("values_file"):
            cmd += ["-f", values]
        rc, out, errtxt = _run(cmd, timeout=300.0)
        if rc != 0:
            return ExecResult(ok=False, detail=f"helm upgrade failed: {errtxt.strip() or out.strip()}")
        return ExecResult(ok=True, detail=f"released {release}", outputs={"release": release})


class TerraformExecutor(BaseExecutor):
    """`terraform apply -auto-approve` in payload['module_dir']. target is
    a label for logging. State backend is the module's concern."""

    kind: ClassVar[str] = "terraform-apply"

    async def execute(self, step: DeploymentStep) -> ExecResult:
        if (err := _cli_or_error("terraform")) is not None:
            return err
        module = step.payload.get("module_dir")
        if not module:
            return ExecResult(ok=False, detail="terraform-apply requires payload.module_dir")
        rc, out, errtxt = _run(["terraform", f"-chdir={module}", "init", "-input=false"], timeout=300.0)
        if rc != 0:
            return ExecResult(ok=False, detail=f"terraform init failed: {errtxt.strip() or out.strip()}")
        rc, out, errtxt = _run(
            ["terraform", f"-chdir={module}", "apply", "-auto-approve", "-input=false"],
            timeout=600.0,
        )
        if rc != 0:
            return ExecResult(ok=False, detail=f"terraform apply failed: {errtxt.strip() or out.strip()}")
        return ExecResult(ok=True, detail=f"applied module {module}", outputs={"module": module})

    async def diff(self, step: DeploymentStep) -> DiffResult:
        """`terraform plan -detailed-exitcode`: 0 = no changes, 2 = changes
        present (drift), 1 = error. Map 0→in-sync, 2→drifted, else unchecked
        (fail-safe). Runs `init` first so a fresh checkout can plan."""
        if shutil.which("terraform") is None:
            return DiffResult(checked=False, detail="terraform not found on PATH")
        module = step.payload.get("module_dir")
        if not module:
            return DiffResult(checked=False, detail="terraform diff requires payload.module_dir")
        rc, _out, errtxt = _run(["terraform", f"-chdir={module}", "init", "-input=false"], timeout=300.0)
        if rc != 0:
            return DiffResult(checked=False, detail=f"terraform init failed: {errtxt.strip()}")
        rc, _out, errtxt = _run(
            ["terraform", f"-chdir={module}", "plan", "-detailed-exitcode", "-input=false"],
            timeout=600.0,
        )
        if rc == 0:
            return DiffResult(checked=True, drifted=False, detail=f"{module}: in sync")
        if rc == 2:
            return DiffResult(checked=True, drifted=True, detail=f"{module}: drift detected")
        return DiffResult(checked=False, detail=f"terraform plan error: {errtxt.strip()}")


class WebhookExecutor(BaseExecutor):
    """POST step.payload['body'] (JSON) to step.target (a URL)."""

    kind: ClassVar[str] = "webhook"

    async def execute(self, step: DeploymentStep) -> ExecResult:
        url = step.target
        if not url:
            return ExecResult(ok=False, detail="webhook requires target (url)")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=step.payload.get("body", {}))
        except httpx.HTTPError as exc:
            return ExecResult(ok=False, detail=f"webhook POST failed: {exc}")
        if resp.status_code >= 400:
            return ExecResult(ok=False, detail=f"webhook returned {resp.status_code}")
        return ExecResult(ok=True, detail=f"posted to {url}", outputs={"status": str(resp.status_code)})
