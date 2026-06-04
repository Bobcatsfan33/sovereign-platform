"""BaseExecutor contract + result type for the executor subsystem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, Field

from ..renderers.artifact import DeploymentStep


class ExecResult(BaseModel):
    """Outcome of executing a single DeploymentStep.

    `ok=False` aborts the rest of the manifest. `detail` is a
    human-readable message; `outputs` carries any structured data the step
    produced (e.g. terraform outputs, the S3 key a put landed at) so later
    steps or the caller can consume it."""

    ok: bool
    detail: str = ""
    outputs: dict[str, str] = Field(default_factory=dict)


class DiffResult(BaseModel):
    """Outcome of a drift check for a single DeploymentStep (ADR-0004).

    Detection is fail-safe: a step whose backend cannot be reached reports
    `checked=False`, which the aggregator treats as `unknown` (NOT drifted),
    so a transient backend blip never triggers a reconcile storm. A
    `drifted=True` result only ever comes from a successful comparison that
    found a difference."""

    #: True when the backend was successfully queried for this step.
    checked: bool = True
    #: True when actual state differs from desired (only meaningful if checked).
    drifted: bool = False
    detail: str = ""


class BaseExecutor(ABC):
    """Implement once per DeploymentStep `kind`. Subclasses set `kind`;
    the registry stores instances keyed by it. Executors must be
    idempotent — re-applying the same step should converge, not duplicate
    (mirrors the renderer apply() contract)."""

    #: The DeploymentStep.kind this executor handles ("k8s-apply", ...).
    kind: ClassVar[str]

    @abstractmethod
    async def execute(self, step: DeploymentStep) -> ExecResult:
        """Apply one step. Must not raise for expected failures — return
        ExecResult(ok=False, ...) so the dispatcher can record the failed
        step and stop cleanly."""
        raise NotImplementedError

    async def diff(self, step: DeploymentStep) -> DiffResult:
        """Report whether actual backend state matches desired for `step`
        (ADR-0004). The default reports in-sync — appropriate for steps with
        nothing to drift (noop/webhook) and a safe fallback for executors
        that have not implemented a real comparison yet. Executors backed by
        a stateful system (k8s, terraform) override this to query the
        backend. Must not raise: return DiffResult(checked=False, ...) when
        the backend cannot be reached."""
        return DiffResult(checked=True, drifted=False, detail=f"{self.kind}: no drift surface")

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None) and not getattr(cls, "kind", None):
            raise TypeError(f"{cls.__name__} must declare a class-level `kind` string")
