"""Data Platform pack renderers — managed database + vector DB.

Like the AI pack, these renderers are pure: `render()` emits a Terraform
module manifest and a single `terraform-apply` DeploymentStep, and
`apply()` delegates to the chassis executor subsystem. This is the second
executor kind proven against the BaseRenderer contract (AI used
`k8s-apply`), demonstrating the Step 0.2 abstraction is backend-agnostic.
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

from .models import ManagedDatabaseParams, VectorDbParams

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _tf_database(params: ManagedDatabaseParams, name: str) -> dict[str, Any]:
    """A minimal Terraform JSON config for a managed RDS-style instance.

    Terraform accepts JSON (.tf.json) natively, so the renderer emits a
    dict the executor writes to module_dir/main.tf.json."""
    return {
        "resource": {
            "aws_db_instance": {
                name: {
                    "identifier": name,
                    "engine": params.engine,
                    "engine_version": params.version,
                    "allocated_storage": params.storage_gb,
                    "instance_class": params.instance_class,
                    "multi_az": params.multi_az,
                    "storage_encrypted": params.encryption_at_rest,
                    "backup_retention_period": params.backup_retention_days,
                    "deletion_protection": params.deletion_protection,
                    "region": params.region,
                    "tags": {
                        "sovereign.pack": "data",
                        "sovereign.classification": params.classification,
                    },
                }
            }
        }
    }


class ManagedDatabaseRenderer(BaseRenderer):
    service_type: ClassVar[str] = "managed-database"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Managed database",
            description="Encrypted, backed-up managed relational database "
            "(Postgres/MySQL) provisioned via Terraform.",
            bindable=True,
            tags=["data", "database", "terraform"],
            pack="data",
            plans=[
                ServicePlan(id="small", name="small", description="db.t3.medium, single-AZ."),
                ServicePlan(id="ha", name="ha", description="Multi-AZ, production."),
            ],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "engine": {"type": "string", "enum": ["postgres", "mysql"], "default": "postgres"},
                        "version": {"type": "string", "default": "16"},
                        "storage_gb": {"type": "integer", "minimum": 10, "default": 20},
                        "multi_az": {"type": "boolean", "default": False},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "encryption_at_rest": {"type": "boolean", "default": True},
                        "backup_retention_days": {"type": "integer", "minimum": 0, "maximum": 35, "default": 7},
                    },
                }
            ),
            metadata={"controls": ["SC-28", "CP-9", "SI-12"], "ui_section": "Data"},
        )

    def _params(self, instance: ServiceInstance) -> ManagedDatabaseParams:
        raw = instance.parameters.model_dump(mode="json")
        extra = raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}
        # tags arrive as strings via the chassis LbParameters.tags dict;
        # coerce the typed fields the model needs.
        coerced: dict[str, Any] = dict(extra)
        for intf in ("storage_gb", "backup_retention_days"):
            if intf in coerced:
                coerced[intf] = int(coerced[intf])
        for boolf in ("multi_az", "encryption_at_rest", "deletion_protection"):
            if boolf in coerced:
                coerced[boolf] = str(coerced[boolf]).lower() in {"1", "true", "yes"}
        return ManagedDatabaseParams.model_validate(coerced)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        tf = _tf_database(params, name)
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"main.tf.json": json.dumps(tf, indent=2, sort_keys=True).encode()},
            metadata={
                "engine": params.engine,
                "classification": params.classification,
                "encryption_at_rest": params.encryption_at_rest,
            },
            deployment_manifest=[
                DeploymentStep(
                    kind="terraform-apply",
                    target=name,
                    payload={"module_dir": f"/artifacts/{name}"},
                )
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
            return ValidationResult(ok=False, errors=["terraform config has no resource block"])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"aws_db_instance.{instance.instance_id}"])


class VectorDbRenderer(BaseRenderer):
    service_type: ClassVar[str] = "vector-db"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Vector database",
            description="Managed vector database (pgvector/qdrant/milvus) for "
            "embeddings, provisioned via Terraform.",
            bindable=True,
            tags=["data", "vector-db", "ai"],
            pack="data",
            plans=[ServicePlan(id="standard", name="standard", description="Single-node.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "store": {"type": "string", "enum": ["pgvector", "qdrant", "milvus"], "default": "pgvector"},
                        "storage_gb": {"type": "integer", "minimum": 10, "default": 20},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "encryption_at_rest": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["SC-28", "SI-12"], "ui_section": "Data"},
        )

    def _params(self, instance: ServiceInstance) -> VectorDbParams:
        raw = instance.parameters.model_dump(mode="json")
        extra = raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}
        coerced: dict[str, Any] = dict(extra)
        if "storage_gb" in coerced:
            coerced["storage_gb"] = int(coerced["storage_gb"])
        if "encryption_at_rest" in coerced:
            coerced["encryption_at_rest"] = str(coerced["encryption_at_rest"]).lower() in {"1", "true", "yes"}
        return VectorDbParams.model_validate(coerced)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        tf = {
            "resource": {
                "sovereign_vector_store": {
                    name: {
                        "store": params.store,
                        "allocated_storage": params.storage_gb,
                        "storage_encrypted": params.encryption_at_rest,
                        "region": params.region,
                    }
                }
            }
        }
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"main.tf.json": json.dumps(tf, indent=2, sort_keys=True).encode()},
            metadata={"store": params.store, "classification": params.classification},
            deployment_manifest=[
                DeploymentStep(
                    kind="terraform-apply",
                    target=name,
                    payload={"module_dir": f"/artifacts/{name}"},
                )
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
        return TeardownResult(ok=True, removed=[f"sovereign_vector_store.{instance.instance_id}"])
