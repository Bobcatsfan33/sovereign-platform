"""Entry-point-driven pack discovery.

Walks the `sovereign.packs` entry-point group at startup, instantiates
each Pack class, calls its `register()`, and records the manifest. The
result is observable via `registered_packs()` — services surface this on
/healthz so an operator can see which packs are active in a deployment.

In tests, `register_pack(pack_instance)` lets us bypass entry points
and register a Pack subclass directly.
"""

from __future__ import annotations

import logging
import threading
from importlib import metadata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BasePack

logger = logging.getLogger("sovereign.packs")

ENTRY_POINT_GROUP = "sovereign.packs"


class PackRegistry:
    def __init__(self) -> None:
        self._packs: dict[str, BasePack] = {}
        self._lock = threading.Lock()

    def add(self, pack: BasePack) -> None:
        with self._lock:
            self._packs[pack.name] = pack

    def all(self) -> list[BasePack]:
        with self._lock:
            return list(self._packs.values())

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._packs.keys())

    def clear(self) -> None:
        with self._lock:
            self._packs.clear()


registry = PackRegistry()


def register_pack(pack: BasePack) -> None:
    """Register a single pack instance. Calls its register() and records
    the pack for later inspection. Idempotent."""
    pack.register()
    registry.add(pack)


def discover_packs() -> list[BasePack]:
    """Discover and register every pack declared via the `sovereign.packs`
    entry point. Returns the list of newly-loaded Pack instances.

    Discovery failures (import errors, bad Pack class, register()
    exceptions) are logged but do NOT abort startup — the chassis is
    designed to come up even if a pack is broken. Operators see the
    failure in logs and on /healthz (missing pack manifest)."""
    # Python >=3.11: entry_points(group=...) returns an EntryPoints object.
    # The project requires-python is >=3.11 so we don't need the legacy
    # dict-shaped fallback the older importlib.metadata had.
    discovered: list[BasePack] = []
    eps = metadata.entry_points(group=ENTRY_POINT_GROUP)

    for ep in eps:
        try:
            cls = ep.load()
            pack = cls()
            register_pack(pack)
            discovered.append(pack)
            logger.info("discovered pack %r v%s (from %s)", pack.name, pack.version, ep.value)
        except Exception:  # noqa: BLE001
            logger.exception("failed to discover pack from entry point %r", ep.name)

    return discovered


def registered_packs() -> list[dict]:
    """Manifest list for every registered pack — what /healthz surfaces."""
    return [p.manifest() for p in registry.all()]
