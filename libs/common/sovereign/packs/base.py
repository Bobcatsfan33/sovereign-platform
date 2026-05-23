"""BasePack — the contract every pack implements.

Subclasses populate the class-level lists; calling `register()` wires
each entry into the chassis registries (renderer registry, connector
registry, catalog store on demand). Packs are idempotent: register()
can be called multiple times without duplicating registrations because
the underlying registries upsert.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from ..catalog import (
        ConnectorCatalogEntry,
        ServiceCatalogEntry,
    )
    from ..connectors.base import BaseConnector
    from ..renderers.base import BaseRenderer

logger = logging.getLogger("sovereign.packs")


class BasePack:
    """Base class for a Sovereign service pack.

    Subclasses set the class-level attributes — they are intentionally
    plain Python attributes (not pydantic) because they hold class
    references. A typical pack looks like::

        class Pack(BasePack):
            name = "sovereign-ai-pack"
            version = "0.3.0"
            renderers = [InferenceEndpointRenderer, RagWorkspaceRenderer]
            connectors = [SharePointConnector, ConfluenceConnector]
            policy_bundles = [Path(__file__).parent / "policies"]
    """

    #: Human-readable pack identifier. Must be unique across installed packs.
    name: ClassVar[str] = ""
    version: ClassVar[str] = "0.0.0"
    description: ClassVar[str] = ""

    renderers: ClassVar[list[type[BaseRenderer]]] = []
    connectors: ClassVar[list[type[BaseConnector]]] = []
    policy_bundles: ClassVar[list[Path]] = []

    #: Extra service catalog entries beyond what renderers auto-publish.
    #: Useful for UI-only service types or pre-launch entries that aren't
    #: yet backed by a renderer.
    extra_service_catalog: ClassVar[list[ServiceCatalogEntry]] = []
    extra_connector_catalog: ClassVar[list[ConnectorCatalogEntry]] = []

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.name:
            raise TypeError(
                f"{cls.__name__} must declare a class-level `name` string"
            )

    def register(self) -> None:
        """Wire every renderer + connector into the chassis registries.
        Catalog entries are seeded by the broker at startup (which walks
        the renderer/connector registries) — packs don't need to talk
        to DynamoDB themselves."""
        # Local imports to avoid a circular import at module load:
        # base.py is part of sovereign.packs; renderers/connectors
        # depend on catalog which depends on settings; clean either
        # direction is fine but lazy resolution is simpler here.
        from ..connectors import register_connector
        from ..renderers import register_renderer

        for renderer_cls in self.renderers:
            try:
                register_renderer(renderer_cls())
            except Exception:  # noqa: BLE001
                logger.exception("pack %r: failed to register renderer %s",
                                 self.name, renderer_cls.__name__)
        for connector_cls in self.connectors:
            try:
                register_connector(connector_cls)
            except Exception:  # noqa: BLE001
                logger.exception("pack %r: failed to register connector %s",
                                 self.name, connector_cls.__name__)
        logger.info(
            "pack %r registered: %d renderers, %d connectors, %d policy bundles",
            self.name,
            len(self.renderers),
            len(self.connectors),
            len(self.policy_bundles),
        )

    def manifest(self) -> dict:
        """Summary of what this pack provides. Surfaced by the chassis
        on /healthz and used by operators to inventory installed packs."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "renderers": [
                getattr(r, "service_type", r.__name__) for r in self.renderers
            ],
            "connectors": [
                getattr(c, "connector_type", c.__name__) for c in self.connectors
            ],
            "policy_bundles": [str(p) for p in self.policy_bundles],
            "extra_service_catalog": [e.service_type for e in self.extra_service_catalog],
            "extra_connector_catalog": [e.connector_type for e in self.extra_connector_catalog],
        }
