"""Tests for the release workflow + changelog tooling (E7)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml
from sovereign.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_changelog_heading_mapping() -> None:
    ce = _load("changelog_extract")
    assert ce.changelog_heading_version("0.5.0a0") == "0.5.0-alpha"
    assert ce.changelog_heading_version("1.2.0b1") == "1.2.0-beta"
    assert ce.changelog_heading_version("1.2.0rc2") == "1.2.0-rc"
    assert ce.changelog_heading_version("1.2.0") == "1.2.0"


def test_current_version_has_changelog_notes() -> None:
    """A release of the current version must have notes to publish."""
    ce = _load("changelog_extract")
    body = ce.extract(__version__, (ROOT / "CHANGELOG.md").read_text())
    assert body, f"CHANGELOG has no section for {__version__}"
    assert "release" in body.lower()


def test_extract_returns_only_the_requested_section() -> None:
    ce = _load("changelog_extract")
    changelog = (
        "# Changelog\n\n"
        "## [0.2.0] — 2026-01-01\nsecond section\n\n"
        "## [0.1.0] — 2025-12-01\nfirst section\n"
    )
    assert ce.extract("0.2.0", changelog) == "second section"
    assert ce.extract("0.1.0", changelog) == "first section"
    assert ce.extract("9.9.9", changelog) == ""


def test_release_workflow_triggers_on_version_tags() -> None:
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    # PyYAML parses the bare `on:` key as boolean True.
    triggers = wf.get("on", wf.get(True))
    assert "v*" in triggers["push"]["tags"]
    assert wf["permissions"]["contents"] == "write"
    steps = wf["jobs"]["release"]["steps"]
    run_blocks = " ".join(s.get("run", "") for s in steps)
    assert "pyproject version" in run_blocks  # tag/version guard present
