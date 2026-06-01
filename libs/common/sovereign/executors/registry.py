"""Executor registry — DeploymentStep.kind -> BaseExecutor instance.

Mirrors the renderer registry: a thread-safe process-wide singleton.
Packs register custom executors (or override chassis ones) at import time
via `register_executor(MyExecutor())`.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseExecutor

logger = logging.getLogger("sovereign.executors")


class ExecutorRegistry:
    """Thread-safe registry of `kind` -> `BaseExecutor`."""

    def __init__(self) -> None:
        self._executors: dict[str, BaseExecutor] = {}
        self._lock = threading.Lock()

    def register(self, executor: BaseExecutor) -> None:
        kind = getattr(executor, "kind", None)
        if not kind:
            raise ValueError(f"{type(executor).__name__} has no `kind` — cannot register")
        with self._lock:
            prior = self._executors.get(kind)
            self._executors[kind] = executor
        if prior is not None and type(prior) is not type(executor):
            logger.warning(
                "executor for %r replaced: %s -> %s",
                kind,
                type(prior).__name__,
                type(executor).__name__,
            )
        else:
            logger.info("registered executor: %s -> %s", kind, type(executor).__name__)

    def get(self, kind: str) -> BaseExecutor | None:
        with self._lock:
            return self._executors.get(kind)

    def kinds(self) -> list[str]:
        with self._lock:
            return sorted(self._executors.keys())

    def clear(self) -> None:
        with self._lock:
            self._executors.clear()


registry = ExecutorRegistry()


def register_executor(executor: BaseExecutor) -> None:
    """Convenience wrapper around `registry.register`."""
    registry.register(executor)


def get_executor(kind: str) -> BaseExecutor | None:
    """Convenience wrapper around `registry.get`."""
    return registry.get(kind)
