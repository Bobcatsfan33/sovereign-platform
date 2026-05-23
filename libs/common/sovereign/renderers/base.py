"""Abstract base class for service-type renderers.

A renderer is the entire lifecycle of a single service type — generating
the platform-managed configuration for an instance, validating it before
deployment, applying it to the target system, and removing it on
deprovision. Adding a new service type means subclassing `BaseRenderer`,
implementing four methods, and registering the class with `registry`.

Concrete renderers live in the chassis (`EnvoyRenderer`) or in service
packs (`InferenceEndpointRenderer`, `SiemWorkspaceRenderer`, ...).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from ..models import ServiceInstance
from .artifact import (
    ApplyResult,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
)

if TYPE_CHECKING:
    from ..catalog import ServiceCatalogEntry


class BaseRenderer(ABC):
    """Implement this once per service type. Subclasses must set the
    `service_type` class attribute — it's the key under which the
    registry stores them and the discriminator the broker uses to pick
    the right renderer for an incoming provision request."""

    #: Stable identifier for the kind of service this renderer manages.
    #: e.g. "sovereign-envoy-lb", "inference-endpoint", "siem-workspace".
    service_type: ClassVar[str]

    @abstractmethod
    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        """Generate config artifacts for `instance`. May raise on
        invalid inputs (the chassis converts to 422 problem detail)."""
        raise NotImplementedError

    @abstractmethod
    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        """Check that `artifact` is safe to deploy. Called after render
        and after `apply` for post-deployment verification. Returning
        `ok=False` aborts the apply."""
        raise NotImplementedError

    @abstractmethod
    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        """Push the artifact to the target system. Executes
        `artifact.deployment_manifest` in order. Idempotent — repeated
        calls with the same artifact should converge to the same end
        state, not duplicate side effects."""
        raise NotImplementedError

    @abstractmethod
    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        """Remove all artifacts and live resources for `instance`. Called
        on deprovision. Best-effort: a non-fatal failure is logged but
        does not block the deprovision response."""
        raise NotImplementedError

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry | None:
        """Optional catalog metadata. Override in subclasses that should
        appear in `GET /v2/catalog`. Returning None hides the service
        type from the public catalog (useful for system/internal types
        a pack uses but does not surface to end users)."""
        return None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Enforce that every concrete subclass declares its service_type
        # so a typo can't silently leave a renderer un-discoverable.
        if not getattr(cls, "__abstractmethods__", None) and not getattr(cls, "service_type", None):
            raise TypeError(
                f"{cls.__name__} must declare a class-level `service_type` string"
            )
