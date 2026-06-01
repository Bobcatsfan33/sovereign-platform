"""Identity pack renderers — IdP broker + SCIM bridge.

Config-driven service types (like FinOps): there is no infrastructure to
deploy, so render() produces a configuration artifact and an empty
deployment manifest, and apply() is a no-op success. The pack's value is
its IA-family policy bundle plus the catalog surface that lets an agency
self-service-bind an IdP/SCIM source to the chassis identity plane.
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

from .models import IdpBrokerParams, ScimBridgeParams

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _tags(instance: ServiceInstance) -> dict[str, Any]:
    raw = instance.parameters.model_dump(mode="json")
    return raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}


class IdpBrokerRenderer(BaseRenderer):
    service_type: ClassVar[str] = "idp-broker"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="IdP broker",
            description="Bind an agency OIDC/SAML identity provider to the chassis "
            "identity plane with MFA + assurance-level enforcement.",
            bindable=False,
            tags=["identity", "oidc", "iam"],
            pack="identity",
            plans=[ServicePlan(id="standard", name="standard", description="One bound IdP.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "required": ["issuer_url"],
                    "properties": {
                        "issuer_url": {"type": "string"},
                        "protocol": {"type": "string", "enum": ["oidc", "saml"], "default": "oidc"},
                        "required_aal": {"type": "string", "enum": ["aal1", "aal2", "aal3"], "default": "aal2"},
                        "require_mfa": {"type": "boolean", "default": True},
                        "allow_piv_cac": {"type": "boolean", "default": True},
                        "max_token_minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 60},
                    },
                }
            ),
            metadata={"controls": ["IA-2", "IA-2(1)", "IA-2(12)", "IA-8"], "ui_section": "Identity"},
        )

    def _params(self, instance: ServiceInstance) -> IdpBrokerParams:
        extra = dict(_tags(instance))
        merged: dict[str, Any] = {"issuer_url": extra.get("issuer_url", f"https://idp/{instance.instance_id}"), **extra}
        if "max_token_minutes" in merged:
            merged["max_token_minutes"] = int(merged["max_token_minutes"])
        for boolf in ("require_mfa", "allow_piv_cac"):
            if boolf in merged:
                merged[boolf] = str(merged[boolf]).lower() in {"1", "true", "yes"}
        return IdpBrokerParams.model_validate(merged)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        config = {
            "issuer_url": params.issuer_url,
            "protocol": params.protocol,
            "required_aal": params.required_aal,
            "require_mfa": params.require_mfa,
            "allow_piv_cac": params.allow_piv_cac,
            "max_token_minutes": params.max_token_minutes,
        }
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"idp.json": json.dumps(config, indent=2, sort_keys=True).encode()},
            metadata={"protocol": params.protocol, "required_aal": params.required_aal},
            deployment_manifest=[],  # config-only; nothing to deploy
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("idp.json")
        if body is None:
            return ValidationResult(ok=False, errors=["missing idp.json"])
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        # Config-only service: the binding is consumed by the broker's
        # identity layer, there is no external apply step.
        return ApplyResult(ok=True)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"idp-broker/{instance.instance_id}"])


class ScimBridgeRenderer(BaseRenderer):
    service_type: ClassVar[str] = "scim-bridge"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="SCIM bridge",
            description="Sync a SCIM 2.0 directory's group membership into chassis "
            "RoleBindings, with automatic deprovisioning.",
            bindable=False,
            tags=["identity", "scim", "iam"],
            pack="identity",
            plans=[ServicePlan(id="standard", name="standard", description="One SCIM source.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "required": ["endpoint_url"],
                    "properties": {
                        "endpoint_url": {"type": "string"},
                        "sync_interval_minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 15},
                        "deprovision_on_remove": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["IA-4", "AC-2", "IA-8"], "ui_section": "Identity"},
        )

    def _params(self, instance: ServiceInstance) -> ScimBridgeParams:
        extra = dict(_tags(instance))
        merged: dict[str, Any] = {"endpoint_url": extra.get("endpoint_url", f"https://scim/{instance.instance_id}"), **extra}
        if "sync_interval_minutes" in merged:
            merged["sync_interval_minutes"] = int(merged["sync_interval_minutes"])
        if "deprovision_on_remove" in merged:
            merged["deprovision_on_remove"] = str(merged["deprovision_on_remove"]).lower() in {"1", "true", "yes"}
        return ScimBridgeParams.model_validate(merged)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        config = {
            "endpoint_url": params.endpoint_url,
            "sync_interval_minutes": params.sync_interval_minutes,
            "deprovision_on_remove": params.deprovision_on_remove,
        }
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"scim.json": json.dumps(config, indent=2, sort_keys=True).encode()},
            metadata={"sync_interval_minutes": params.sync_interval_minutes},
            deployment_manifest=[],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("scim.json")
        if body is None:
            return ValidationResult(ok=False, errors=["missing scim.json"])
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return ApplyResult(ok=True)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"scim-bridge/{instance.instance_id}"])
