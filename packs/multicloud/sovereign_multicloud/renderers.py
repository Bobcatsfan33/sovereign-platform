"""Multi-Cloud pack renderers — cloud account + landing zone.

Pure renderers emitting Terraform JSON + a `terraform-apply` step (reuses
the Data pack's executor path across a different provider surface). The
compliance value is the residency/governance policy bundle.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from sovereign.executors import apply_manifest
from sovereign.renderers import (
    ApplyResult,
    BaseRenderer,
    DeploymentStep,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
)

from .models import CloudAccountParams, LandingZoneParams

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _tags(instance: ServiceInstance) -> dict[str, Any]:
    raw = instance.parameters.model_dump(mode="json")
    return raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}


def _coerce_bool(d: dict[str, Any], *keys: str) -> None:
    for k in keys:
        if k in d:
            d[k] = str(d[k]).lower() in {"1", "true", "yes"}


class CloudAccountRenderer(BaseRenderer):
    service_type: ClassVar[str] = "cloud-account"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Cloud account",
            description="Provision a governed cloud account/subscription baseline "
            "(guardrails + org audit) in an approved government region.",
            bindable=False,
            tags=["multi-cloud", "account", "terraform"],
            pack="multicloud",
            plans=[ServicePlan(id="baseline", name="baseline", description="Guardrailed account.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "enum": ["aws-govcloud", "azure-gov", "gcp"], "default": "aws-govcloud"},
                        "region": {"type": "string", "default": "us-gov-west-1"},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "guardrails_enabled": {"type": "boolean", "default": True},
                        "org_audit_enabled": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["CM-2", "AU-2", "AC-4"], "ui_section": "Multi-Cloud"},
        )

    def _params(self, instance: ServiceInstance) -> CloudAccountParams:
        extra = dict(_tags(instance))
        _coerce_bool(extra, "guardrails_enabled", "org_audit_enabled")
        return CloudAccountParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        tf = {
            "resource": {
                "sovereign_cloud_account": {
                    name: {
                        "provider": params.provider,
                        "region": params.region,
                        "guardrails_enabled": params.guardrails_enabled,
                        "org_audit_enabled": params.org_audit_enabled,
                        "tags": {
                            "sovereign.pack": "multicloud",
                            "sovereign.classification": params.classification,
                        },
                    }
                }
            }
        }
        return RenderedArtifact(
            instance_id=name,
            service_type=self.service_type,
            version=instance.version,
            config_files={"main.tf.json": json.dumps(tf, indent=2, sort_keys=True).encode()},
            metadata={"provider": params.provider, "region": params.region, "classification": params.classification},
            deployment_manifest=[
                DeploymentStep(kind="terraform-apply", target=name, payload={"module_dir": f"/artifacts/{name}"})
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("main.tf.json")
        if body is None:
            return ValidationResult(ok=False, errors=["missing main.tf.json"])
        try:
            doc = json.loads(body)
        except json.JSONDecodeError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        if "resource" not in doc:
            return ValidationResult(ok=False, errors=["no resource block"])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"sovereign_cloud_account.{instance.instance_id}"])


class LandingZoneRenderer(BaseRenderer):
    service_type: ClassVar[str] = "landing-zone"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Landing zone",
            description="Multi-account landing zone (hub/spoke networking + baseline "
            "accounts) in an approved government region.",
            bindable=False,
            tags=["multi-cloud", "landing-zone", "terraform"],
            pack="multicloud",
            plans=[ServicePlan(id="standard", name="standard", description="3-account zone.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "enum": ["aws-govcloud", "azure-gov", "gcp"], "default": "aws-govcloud"},
                        "region": {"type": "string", "default": "us-gov-west-1"},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "account_count": {"type": "integer", "minimum": 1, "maximum": 100, "default": 3},
                        "network_boundary": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["SC-7", "CM-2", "AC-4"], "ui_section": "Multi-Cloud"},
        )

    def _params(self, instance: ServiceInstance) -> LandingZoneParams:
        extra = dict(_tags(instance))
        if "account_count" in extra:
            extra["account_count"] = int(extra["account_count"])
        _coerce_bool(extra, "network_boundary")
        return LandingZoneParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        tf = {
            "resource": {
                "sovereign_landing_zone": {
                    name: {
                        "provider": params.provider,
                        "region": params.region,
                        "account_count": params.account_count,
                        "network_boundary": params.network_boundary,
                    }
                }
            }
        }
        return RenderedArtifact(
            instance_id=name,
            service_type=self.service_type,
            version=instance.version,
            config_files={"main.tf.json": json.dumps(tf, indent=2, sort_keys=True).encode()},
            metadata={"provider": params.provider, "account_count": params.account_count},
            deployment_manifest=[
                DeploymentStep(kind="terraform-apply", target=name, payload={"module_dir": f"/artifacts/{name}"})
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("main.tf.json")
        if body is None:
            return ValidationResult(ok=False, errors=["missing main.tf.json"])
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"sovereign_landing_zone.{instance.instance_id}"])
