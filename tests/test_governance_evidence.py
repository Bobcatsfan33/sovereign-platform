"""Governance/evidence regression checks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pr_template_requires_security_review() -> None:
    template = (ROOT / ".github" / "pull_request_template.md").read_text()

    assert "security-reviewer" in template
    assert "authentication, authorization, tenancy, secrets, audit" in template
    assert "SSP/POA&M evidence" in template
    assert "make check" in template


def test_fastapi_startup_uses_lifespan_not_deprecated_on_event() -> None:
    checked = [
        path
        for root in (ROOT / "apps", ROOT / "libs")
        for path in root.rglob("*.py")
    ]

    offenders = [
        str(path.relative_to(ROOT))
        for path in checked
        if "on_event(" in path.read_text()
    ]
    assert offenders == []


def test_ssp_no_longer_claims_latest_image_promotion() -> None:
    cm = (ROOT / "docs" / "ssp" / "controls" / "cm.md").read_text()
    si = (ROOT / "docs" / "ssp" / "controls" / "si.md").read_text()

    assert "latest is set" not in cm
    assert "never reach `latest`" not in si
