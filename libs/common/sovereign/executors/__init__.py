"""Deployment executor subsystem (Step 0.2).

A renderer produces a `RenderedArtifact` whose `deployment_manifest` is an
ordered list of `DeploymentStep`s. Until now the only thing that knew how
to *apply* a step was the Envoy renderer's own `apply()` (S3 put +
snapshot log). That coupling meant every new service type had to
re-implement apply logic, and the `k8s-apply` / `helm-upgrade` /
`terraform-apply` / `webhook` step kinds reserved by `DeploymentStep`
were inert.

This subsystem inverts that: renderers stay *pure* (render → manifest),
and the chassis owns a registry of `BaseExecutor`s keyed by step `kind`.
`apply_manifest()` walks a manifest, dispatches each step to its
executor, and returns an `ApplyResult` — the same shape renderers already
return — so a pack renderer can delegate its entire `apply()` to the
chassis with one call.

Executors are deliberately thin and dependency-light. The Kubernetes /
Helm / Terraform executors shell out to the corresponding CLI (kubectl /
helm / terraform) which is how every real platform applies these anyway;
this keeps the chassis free of heavy client libraries and makes the
executors trivially mockable in tests (patch `_run`). A NoopExecutor
covers `envoy-snapshot`-style "nothing to orchestrate" steps.

Public surface::

    from sovereign.executors import (
        BaseExecutor, registry, register_executor,
        apply_manifest, ExecResult,
    )
"""

from .base import BaseExecutor, DiffResult, ExecResult
from .dispatch import ManifestDiff, apply_manifest, diff_manifest
from .registry import get_executor, register_executor, registry
from .shell import (
    HelmExecutor,
    KubernetesExecutor,
    NoopExecutor,
    TerraformExecutor,
    WebhookExecutor,
)


def register_default_executors() -> None:
    """Register the chassis-shipped executors.

    Service startup calls this before serving traffic so any renderer that
    delegates to ``apply_manifest()`` has the standard execution backends
    available. The registry upserts by kind, so repeated calls are idempotent.
    """
    register_executor(NoopExecutor())
    register_executor(KubernetesExecutor())
    register_executor(HelmExecutor())
    register_executor(TerraformExecutor())
    register_executor(WebhookExecutor())


__all__ = [
    "BaseExecutor",
    "DiffResult",
    "ExecResult",
    "HelmExecutor",
    "KubernetesExecutor",
    "ManifestDiff",
    "NoopExecutor",
    "TerraformExecutor",
    "WebhookExecutor",
    "apply_manifest",
    "diff_manifest",
    "get_executor",
    "register_default_executors",
    "register_executor",
    "registry",
]
