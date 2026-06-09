"""Single-source version consistency (E7)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sovereign.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_matches_version_module() -> None:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'(?m)^version = "([^"]+)"', text)
    assert match is not None
    assert match.group(1) == __version__


@pytest.mark.parametrize(
    "service_dir,module_alias",
    [
        ("broker", "broker_main"),
        ("control-plane", "control_plane_main"),
        ("audit-service", "audit_service_main"),
        ("metering-service", "metering_service_main"),
    ],
)
def test_service_reports_single_version(service_dir: str, module_alias: str) -> None:
    import importlib.util

    path = ROOT / "apps" / service_dir / "app" / "main.py"
    spec = importlib.util.spec_from_file_location(module_alias, str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[module_alias] = module
    spec.loader.exec_module(module)
    assert module.app.version == __version__
