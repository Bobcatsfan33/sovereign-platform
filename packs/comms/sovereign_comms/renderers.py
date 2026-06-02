"""Comms pack renderers — secure email + secure chat.

Config-driven service types (like Identity/FinOps): render() produces a
configuration artifact with an empty deployment manifest and apply() is a
verified no-op. The value is the transmission/retention policy bundle.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from sovereign.renderers import (
    ApplyResult,
    BaseRenderer,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
)

from .models import SecureChatParams, SecureEmailParams

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _tags(instance: ServiceInstance) -> dict[str, Any]:
    raw = instance.parameters.model_dump(mode="json")
    return raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}


def _coerce(d: dict[str, Any], ints: tuple[str, ...] = (), bools: tuple[str, ...] = ()) -> None:
    for k in ints:
        if k in d:
            d[k] = int(d[k])
    for k in bools:
        if k in d:
            d[k] = str(d[k]).lower() in {"1", "true", "yes"}


class SecureEmailRenderer(BaseRenderer):
    service_type: ClassVar[str] = "secure-email"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Secure email",
            description="Governed email relay with TLS, FIPS crypto, DLP, and "
            "long-term retention bound to an agency mail provider.",
            bindable=False,
            tags=["comms", "email", "dlp"],
            pack="comms",
            plans=[ServicePlan(id="standard", name="standard", description="One relay.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "default": "m365-gcc-high"},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "tls_required": {"type": "boolean", "default": True},
                        "cipher_suite": {"type": "string", "default": "TLS_AES_256_GCM_SHA384"},
                        "retention_days": {"type": "integer", "minimum": 1, "default": 2555},
                        "dlp_enabled": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["SC-8", "SC-13", "SI-12", "AU-11"], "ui_section": "Comms"},
        )

    def _params(self, instance: ServiceInstance) -> SecureEmailParams:
        extra = dict(_tags(instance))
        _coerce(extra, ints=("retention_days",), bools=("tls_required", "dlp_enabled"))
        return SecureEmailParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        config = params.model_dump()
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"email.json": json.dumps(config, indent=2, sort_keys=True).encode()},
            metadata={"provider": params.provider, "classification": params.classification},
            deployment_manifest=[],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("email.json")
        if body is None:
            return ValidationResult(ok=False, errors=["missing email.json"])
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return ApplyResult(ok=True)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"secure-email/{instance.instance_id}"])


class SecureChatRenderer(BaseRenderer):
    service_type: ClassVar[str] = "secure-chat"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Secure chat",
            description="Governed chat workspace with TLS, FIPS crypto, retention, "
            "and federation controls.",
            bindable=False,
            tags=["comms", "chat"],
            pack="comms",
            plans=[ServicePlan(id="standard", name="standard", description="One workspace.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "default": "teams-gcc-high"},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "tls_required": {"type": "boolean", "default": True},
                        "cipher_suite": {"type": "string", "default": "TLS_AES_256_GCM_SHA384"},
                        "retention_days": {"type": "integer", "minimum": 1, "default": 365},
                        "external_federation": {"type": "boolean", "default": False},
                    },
                }
            ),
            metadata={"controls": ["SC-8", "SC-13", "AC-4", "SI-12"], "ui_section": "Comms"},
        )

    def _params(self, instance: ServiceInstance) -> SecureChatParams:
        extra = dict(_tags(instance))
        _coerce(extra, ints=("retention_days",), bools=("tls_required", "external_federation"))
        return SecureChatParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        config = params.model_dump()
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"chat.json": json.dumps(config, indent=2, sort_keys=True).encode()},
            metadata={"provider": params.provider, "classification": params.classification},
            deployment_manifest=[],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("chat.json")
        if body is None:
            return ValidationResult(ok=False, errors=["missing chat.json"])
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return ApplyResult(ok=True)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"secure-chat/{instance.instance_id}"])
