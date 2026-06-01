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

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None) and not getattr(cls, "kind", None):
            raise TypeError(f"{cls.__name__} must declare a class-level `kind` string")
