"""Tests for the NIST -> ISO/IEC 27001 control crosswalk (WS4)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _load_validator() -> ModuleType:
    path = ROOT / "scripts" / "crosswalk_validate.py"
    spec = importlib.util.spec_from_file_location("crosswalk_validate", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["crosswalk_validate"] = module
    spec.loader.exec_module(module)
    return module


def test_crosswalk_is_valid() -> None:
    problems = _load_validator().validate()
    assert problems == [], f"crosswalk problems: {problems}"


def test_crosswalk_has_meaningful_coverage() -> None:
    data = json.loads((ROOT / "docs" / "ssp" / "crosswalk.json").read_text())
    assert data["target_framework"].startswith("ISO/IEC 27001")
    assert len(data["mappings"]) >= 25


def test_every_source_control_exists_in_the_ssp() -> None:
    cv = _load_validator()
    data = json.loads((ROOT / "docs" / "ssp" / "crosswalk.json").read_text())
    ssp_ids = cv._ssp_control_ids()
    assert set(data["mappings"]).issubset(ssp_ids)
