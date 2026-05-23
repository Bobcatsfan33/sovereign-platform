"""Connector registry — connector_type -> connector class.

Unlike the renderer registry which stores instances, the connector
registry stores *classes* and instantiates per-call. A connector
instance holds auth state tied to one credential set, so reuse across
tenants would leak state. Callers pull the class, construct, and
connect:

    cls = connector_registry.require("s3")
    conn = cls()
    await conn.connect(credentials)
    items = await conn.list_resources({"bucket": "x"})
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseConnector

logger = logging.getLogger("sovereign.connectors")


class ConnectorRegistry:
    """Thread-safe registry of `connector_type` -> connector class."""

    def __init__(self) -> None:
        self._classes: dict[str, type[BaseConnector]] = {}
        self._lock = threading.Lock()

    def register(self, cls: type[BaseConnector]) -> None:
        connector_type = getattr(cls, "connector_type", None)
        if not connector_type:
            raise ValueError(
                f"{cls.__name__} has no `connector_type` — cannot register"
            )
        with self._lock:
            prior = self._classes.get(connector_type)
            self._classes[connector_type] = cls
        if prior is not None and prior is not cls:
            logger.warning(
                "connector for %r replaced: %s -> %s",
                connector_type,
                prior.__name__,
                cls.__name__,
            )
        else:
            logger.info("registered connector: %s -> %s", connector_type, cls.__name__)

    def get(self, connector_type: str) -> type[BaseConnector] | None:
        with self._lock:
            return self._classes.get(connector_type)

    def require(self, connector_type: str) -> type[BaseConnector]:
        cls = self.get(connector_type)
        if cls is None:
            raise KeyError(
                f"no connector registered for connector_type {connector_type!r}"
            )
        return cls

    def connector_types(self) -> list[str]:
        with self._lock:
            return sorted(self._classes.keys())

    def clear(self) -> None:
        with self._lock:
            self._classes.clear()


registry = ConnectorRegistry()


def register_connector(cls: type[BaseConnector]) -> None:
    """Convenience wrapper around `registry.register`."""
    registry.register(cls)


def get_connector(connector_type: str) -> type[BaseConnector] | None:
    """Convenience wrapper around `registry.get`."""
    return registry.get(connector_type)
