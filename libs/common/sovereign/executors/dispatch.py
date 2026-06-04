"""Manifest dispatcher — walk a deployment_manifest, run each step.

This is what lets a pack renderer delegate its whole `apply()` to the
chassis: render produces the manifest, `apply_manifest()` executes it via
the registry and returns the renderer-native `ApplyResult`. Unknown step
kinds are surfaced as a failed step (not silently skipped) so a manifest
that references an executor the deployment hasn't registered fails loudly.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..renderers.artifact import ApplyResult, DeploymentStep
from .registry import registry as executor_registry

logger = logging.getLogger("sovereign.executors.dispatch")


class ManifestDiff(BaseModel):
    """Aggregate drift result for a whole deployment manifest (ADR-0004).

    `drifted` is True when at least one *successfully checked* step differs
    from desired. `unknown` is True when at least one step could not be
    checked (backend unreachable / missing CLI / no registered executor) —
    detection is fail-safe, so an unchecked step never counts as drift.
    `details` carries the per-step human-readable findings for the audit
    trail."""

    drifted: bool = False
    unknown: bool = False
    details: list[str] = Field(default_factory=list)


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


async def diff_manifest(manifest: list[DeploymentStep]) -> ManifestDiff:
    """Walk every step's `diff()` and aggregate into a ManifestDiff (ADR-0004).

    Mirrors apply_manifest but is read-only and never stops early — every
    step is checked so the audit trail is complete. A step whose kind has no
    registered executor is treated as unknown (fail-safe), not drift."""
    drifted = False
    unknown = False
    details: list[str] = []
    for step in manifest:
        executor = executor_registry.get(step.kind)
        if executor is None:
            unknown = True
            details.append(f"{step.kind}: no executor registered (unchecked)")
            continue
        d = await executor.diff(step)
        if not d.checked:
            unknown = True
            details.append(f"{step.kind}: unchecked — {d.detail}")
        elif d.drifted:
            drifted = True
            details.append(f"{step.kind}: DRIFTED — {d.detail}")
        else:
            details.append(f"{step.kind}: in sync")
    return ManifestDiff(drifted=drifted, unknown=unknown, details=details)
