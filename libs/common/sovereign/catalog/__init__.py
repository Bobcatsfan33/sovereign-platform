"""Service catalog — DynamoDB-backed inventory of service types and connectors.

The catalog is the public face of the platform: `GET /v2/catalog` reads
from it, the UI's "create new service" wizard reads from it, the policy
engine reads it to evaluate `allowed_service_types` rules. Each pack
contributes entries on registration (Phase 1 task 1.9); the broker
bootstraps the chassis-owned entries at startup.

Public surface:

    from sovereign.catalog import (
        CatalogStore,
        ServiceCatalogEntry,
        ServicePlan,
        ConnectorCatalogEntry,
        ParameterSchema,
    )
"""

from .models import (
    ConnectorCatalogEntry,
    ParameterSchema,
    ServiceCatalogEntry,
    ServicePlan,
)
from .store import CatalogStore

__all__ = [
    "CatalogStore",
    "ConnectorCatalogEntry",
    "ParameterSchema",
    "ServiceCatalogEntry",
    "ServicePlan",
]
