"""Pack registration system — discover and load service packs.

A pack is a Python package that ships:
  - one or more BaseRenderer subclasses (e.g. InferenceEndpointRenderer)
  - zero or more BaseConnector subclasses (e.g. SharePointConnector)
  - zero or more OPA policy bundle directories
  - optional catalog entries beyond what the renderers/connectors auto-
    publish (e.g. service types that are surfaced in the UI but have no
    runtime implementation yet)
  - optional UI component metadata

Packs declare themselves via a Python entry point in their pyproject:

    [project.entry-points."sovereign.packs"]
    my_pack = "my_pack:Pack"

`my_pack:Pack` resolves to a subclass of `BasePack`. At service startup,
`discover_packs()` walks the `sovereign.packs` entry-point group,
instantiates each Pack, and calls `register()` on it — which in turn
registers the pack's renderers, connectors, and catalog entries into
the chassis registries.

Public surface:

    from sovereign.packs import (
        BasePack, discover_packs, registered_packs, register_pack
    )
"""

from .base import BasePack
from .discovery import (
    discover_packs,
    register_pack,
    registered_packs,
    registry,
)

__all__ = [
    "BasePack",
    "discover_packs",
    "register_pack",
    "registered_packs",
    "registry",
]
