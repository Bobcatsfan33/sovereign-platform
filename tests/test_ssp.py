"""SSP control package validation (E6).

Keeps the authorization package honest: every control's cited evidence must
resolve to a real file, so the SSP can't drift from the code it claims to
document.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _load_validator() -> ModuleType:
    path = ROOT / "scripts" / "ssp_validate.py"
    spec = importlib.util.spec_from_file_location("ssp_validate", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ssp_validate"] = module
    spec.loader.exec_module(module)
    return module


def test_all_cited_evidence_resolves() -> None:
    report = _load_validator().validate()
    assert report.missing == [], f"SSP cites missing evidence: {report.missing}"


def test_control_coverage_is_meaningful() -> None:
    report = _load_validator().validate()
    # Sanity floor so a control table can't be silently gutted.
    assert len(report.rows) >= 80
    assert report.by_status.get("implemented", 0) >= 60
    # Every control row carried a parseable status.
    assert sum(report.by_status.values()) == len(report.rows)


def test_every_control_id_is_well_formed() -> None:
    import re

    report = _load_validator().validate()
    pattern = re.compile(r"^[A-Z]{2}-\d+(\(\d+\))?$")
    assert all(pattern.match(row.control) for row in report.rows)
