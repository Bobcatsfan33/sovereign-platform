"""Renderer registry — service_type -> BaseRenderer instance.

A process-wide singleton (`registry`) that the broker and control-plane
consult to find the right renderer for a service_type. Service packs
add their renderers via `register_renderer(MyRenderer())` at import
time (typically from a package entry point — see Phase 1 task 1.9).

The registry is intentionally simple: a dict with thread-safe
register/get operations. No version negotiation, no priority resolution.
If a pack wants to override the chassis's renderer for a service type,
it can — the last `register_renderer` call wins, and the chassis logs
the override at startup so the operator sees it.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseRenderer

logger = logging.getLogger("sovereign.renderers")


class RendererRegistry:
    """Thread-safe registry of `service_type` -> `BaseRenderer`."""

    def __init__(self) -> None:
        self._renderers: dict[str, BaseRenderer] = {}
        self._lock = threading.Lock()

    def register(self, renderer: BaseRenderer) -> None:
        """Register `renderer` under its `service_type`. Overriding an
        existing registration is allowed; the override is logged at
        WARNING so it's visible in service startup logs."""
        service_type = getattr(renderer, "service_type", None)
        if not service_type:
            raise ValueError(
                f"{type(renderer).__name__} has no `service_type` — "
                "cannot register"
            )
        with self._lock:
            prior = self._renderers.get(service_type)
            self._renderers[service_type] = renderer
        if prior is not None and type(prior) is not type(renderer):
            logger.warning(
                "renderer for %r replaced: %s -> %s",
                service_type,
                type(prior).__name__,
                type(renderer).__name__,
            )
        else:
            logger.info(
                "registered renderer: %s -> %s",
                service_type,
                type(renderer).__name__,
            )

    def get(self, service_type: str) -> BaseRenderer | None:
        with self._lock:
            return self._renderers.get(service_type)

    def require(self, service_type: str) -> BaseRenderer:
        """Like `get` but raises KeyError if no renderer is registered.
        Callers that surface to HTTP should catch and return 404."""
        renderer = self.get(service_type)
        if renderer is None:
            raise KeyError(f"no renderer registered for service_type {service_type!r}")
        return renderer

    def service_types(self) -> list[str]:
        with self._lock:
            return sorted(self._renderers.keys())

    def clear(self) -> None:
        """Empty the registry. Intended for tests; production code
        should never need this."""
        with self._lock:
            self._renderers.clear()


# Module-level singleton. Services import this directly:
#   from sovereign.renderers import registry
#   await registry.require(req.service_id).render(instance)
registry = RendererRegistry()


def register_renderer(renderer: BaseRenderer) -> None:
    """Convenience wrapper around `registry.register`."""
    registry.register(renderer)


def get_renderer(service_type: str) -> BaseRenderer | None:
    """Convenience wrapper around `registry.get`."""
    return registry.get(service_type)
