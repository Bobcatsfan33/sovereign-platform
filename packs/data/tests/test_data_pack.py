"""Tests for the Data Platform pack (Tier-2, terraform-apply executor)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_data  # noqa: E402
from sovereign_data.models import ManagedDatabaseParams, VectorDbParams  # noqa: E402
from sovereign_data.renderers import (  # noqa: E402
    ManagedDatabaseRenderer,
    VectorDbRenderer,
)


def _instance(instance_id: str = "demo-db", service_id: str = "managed-database", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id=service_id,
        plan_id="small",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


# ── models ────────────────────────────────────────────────────────────


def test_database_params_defaults() -> None:
    p = ManagedDatabaseParams()
    assert p.engine == "postgres"
    assert p.encryption_at_rest is True
    assert p.deletion_protection is True


def test_vector_params_defaults() -> None:
    p = VectorDbParams()
    assert p.store == "pgvector"
    assert p.encryption_at_rest is True


# ── database renderer (terraform-apply) ───────────────────────────────


async def test_database_render_emits_terraform_step() -> None:
    r = ManagedDatabaseRenderer()
    artifact = await r.render(_instance(engine="postgres"))
    assert "main.tf.json" in artifact.config_files
    assert len(artifact.deployment_manifest) == 1
    step = artifact.deployment_manifest[0]
    # The defining difference from the AI pack: this drives terraform-apply.
    assert step.kind == "terraform-apply"
    assert step.payload["module_dir"].endswith(artifact.instance_id)


async def test_database_render_terraform_is_valid_json() -> None:
    r = ManagedDatabaseRenderer()
    artifact = await r.render(_instance("pgdb", storage_gb=50, multi_az=True))
    doc = json.loads(artifact.config_files["main.tf.json"])
    db = doc["resource"]["aws_db_instance"]["pgdb"]
    assert db["allocated_storage"] == 50
    assert db["multi_az"] is True
    assert db["storage_encrypted"] is True


async def test_database_validate_ok_and_apply_delegates() -> None:
    from sovereign.executors import register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, ExecResult

    r = ManagedDatabaseRenderer()
    artifact = await r.render(_instance("d1"))
    assert (await r.validate(artifact)).ok

    ex_registry.clear()

    class _FakeTf(BaseExecutor):
        kind = "terraform-apply"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True, detail=f"applied {step.target}", outputs={"module": step.target})

    register_executor(_FakeTf())
    ar = await r.apply(artifact)
    assert ar.ok
    assert len(ar.applied_steps) == 1


async def test_database_validate_rejects_garbage() -> None:
    from sovereign.renderers import RenderedArtifact

    r = ManagedDatabaseRenderer()
    bad = RenderedArtifact(
        instance_id="x",
        service_type="managed-database",
        version=1,
        config_files={"main.tf.json": b"{not json"},
    )
    assert not (await r.validate(bad)).ok


# ── vector db renderer ────────────────────────────────────────────────


async def test_vector_render_emits_terraform_step() -> None:
    r = VectorDbRenderer()
    artifact = await r.render(_instance("vec1", service_id="vector-db", store="qdrant"))
    doc = json.loads(artifact.config_files["main.tf.json"])
    assert "sovereign_vector_store" in doc["resource"]
    assert artifact.deployment_manifest[0].kind == "terraform-apply"


# ── catalog ───────────────────────────────────────────────────────────


def test_database_catalog_entry_shape() -> None:
    e = ManagedDatabaseRenderer.catalog_entry()
    assert e.service_type == "managed-database"
    assert e.pack == "data"
    assert "CP-9" in e.metadata["controls"]


def test_vector_catalog_entry_shape() -> None:
    e = VectorDbRenderer.catalog_entry()
    assert e.service_type == "vector-db"
    assert "SC-28" in e.metadata["controls"]


# ── registration ──────────────────────────────────────────────────────


def test_pack_registers_renderers_and_bundle() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_data.Pack())
    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-data-pack" in names
    assert "managed-database" in renderer_registry.service_types()
    assert "vector-db" in renderer_registry.service_types()

    pack = sovereign_data.Pack()
    assert (pack.policy_bundles[0] / "data.rego").exists()
