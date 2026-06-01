"""Manifest dispatcher — walk a deployment_manifest, run each step.

This is what lets a pack renderer delegate its whole `apply()` to the
chassis: render produces the manifest, `apply_manifest()` executes it via
the registry and returns the renderer-native `ApplyResult`. Unknown step
kinds are surfaced as a failed step (not silently skipped) so a manifest
that references an executor the deployment hasn't registered fails loudly.
"""

from __future__ import annotations

import logging

from ..renderers.artifact import ApplyResult, DeploymentStep
from .registry import registry as executor_registry

logger = logging.getLogger("sovereign.executors.dispatch")


async def apply_manifest(manifest: list[DeploymentStep]) -> ApplyResult:
    """Execute each step in order through its registered executor.

    Stops at the first failure, returning the steps applied so far plus
    the failed step and its detail — the same ApplyResult shape every
    BaseRenderer.apply() returns, so callers treat chassis-applied and
    renderer-applied results identically."""
    applied: list[DeploymentStep] = []
    for step in manifest:
        executor = executor_registry.get(step.kind)
        if executor is None:
            return ApplyResult(
                ok=False,
                applied_steps=applied,
                failed_step=step,
                detail=f"no executor registered for step kind {step.kind!r}",
            )
        result = await executor.execute(step)
        if not result.ok:
            return ApplyResult(
                ok=False,
                applied_steps=applied,
                failed_step=step,
                detail=result.detail,
            )
        applied.append(step)
    return ApplyResult(ok=True, applied_steps=applied)
