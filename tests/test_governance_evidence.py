"""Governance/evidence regression checks."""

from __future__ import annotations

import re
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


def _markdown_section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = text.find("\n## ", start + len(heading))
    return text[start:] if following == -1 else text[start:following]


def test_poam_open_table_does_not_contain_closed_items() -> None:
    poam = (ROOT / "docs" / "ssp" / "poam.md").read_text()
    open_items = _markdown_section(poam, "## Open items")
    closed_items = _markdown_section(poam, "## Closed items")

    assert "closed" not in open_items.lower()
    assert "5.4-B" not in open_items
    assert "5.4-B" in closed_items
    assert ":latest-rootless" not in open_items


def test_trivy_allowlist_poam_references_are_tracked() -> None:
    poam = (ROOT / "docs" / "ssp" / "poam.md").read_text()
    trivyignore = (ROOT / ".trivyignore").read_text()
    referenced_ids = set(re.findall(r"POA&M (5\.4-CVE-[A-Za-z0-9-]+)", trivyignore))

    assert referenced_ids
    for item_id in referenced_ids:
        assert f"| {item_id} |" in poam


def test_stig_hardening_reflects_closed_cosign_work() -> None:
    stig = (ROOT / "docs" / "stig-hardening.md").read_text()
    open_items = _markdown_section(stig, "## Chassis-side hardening (POA&M open items)")

    assert "Image signing and provenance verification" in stig
    assert "Sign every chassis image with cosign" not in open_items
