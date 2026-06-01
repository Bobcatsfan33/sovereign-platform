"""Tests for pack policy-bundle collection (Step 0.3)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from sovereign.packs import BasePack, register_pack
from sovereign.packs import registry as pack_registry
from sovereign.packs.policy_bundles import collect_policy_bundle_dirs


def test_collects_existing_bundle_dirs(tmp_path: Path) -> None:
    pack_registry.clear()
    bundle = tmp_path / "policies"
    bundle.mkdir()

    class _Pack(BasePack):
        name = "bundle-pack"
        version = "0.1.0"
        policy_bundles: ClassVar[list] = [bundle]

    register_pack(_Pack())
    dirs = collect_policy_bundle_dirs()
    assert str(bundle) in dirs


def test_skips_missing_bundle_dirs(tmp_path: Path) -> None:
    pack_registry.clear()

    class _Pack(BasePack):
        name = "missing-bundle-pack"
        version = "0.1.0"
        policy_bundles: ClassVar[list] = [tmp_path / "does-not-exist"]

    register_pack(_Pack())
    assert collect_policy_bundle_dirs() == []


def test_dedupes_across_packs(tmp_path: Path) -> None:
    pack_registry.clear()
    shared = tmp_path / "shared"
    shared.mkdir()

    class _A(BasePack):
        name = "a-pack"
        version = "0.1.0"
        policy_bundles: ClassVar[list] = [shared]

    class _B(BasePack):
        name = "b-pack"
        version = "0.1.0"
        policy_bundles: ClassVar[list] = [shared]

    register_pack(_A())
    register_pack(_B())
    dirs = collect_policy_bundle_dirs()
    assert dirs.count(str(shared)) == 1


def test_empty_when_no_packs() -> None:
    pack_registry.clear()
    assert collect_policy_bundle_dirs() == []
