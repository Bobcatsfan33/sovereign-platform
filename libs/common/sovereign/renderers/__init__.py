"""Renderer subsystem — pluggable per-service-type config generators.

A renderer takes a `ServiceInstance` and produces a `RenderedArtifact`
(config files + metadata + deployment manifest). Renderers are registered
by their `service_type` string; the broker / control-plane look up the
right renderer at provision time. New service types are added by
implementing `BaseRenderer` and registering it — no broker code changes.

Public surface:

    from sovereign.renderers import (
        BaseRenderer,              # implement this to add a renderer
        RenderedArtifact,          # bundle produced by render()
        DeploymentStep,            # one action in a deployment manifest
        ValidationResult,
        ApplyResult,
        TeardownResult,
        registry,                  # global renderer registry instance
        get_renderer,              # registry shorthand
        register_renderer,
    )
"""

from .artifact import (
    ApplyResult,
    DeploymentStep,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
)
from .base import BaseRenderer
from .registry import get_renderer, register_renderer, registry

__all__ = [
    "ApplyResult",
    "BaseRenderer",
    "DeploymentStep",
    "RenderedArtifact",
    "TeardownResult",
    "ValidationResult",
    "get_renderer",
    "register_renderer",
    "registry",
]
