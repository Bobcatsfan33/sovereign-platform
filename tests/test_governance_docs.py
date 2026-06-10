"""WS6: the security policy + governance contract exist and carry the
elements an enterprise operations org relies on (kept honest by a test so they
can't silently degrade to placeholders)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_security_policy_has_required_elements() -> None:
    text = (ROOT / "SECURITY.md").read_text()
    assert "Reporting a Vulnerability" in text
    assert "Supported Versions" in text
    # A response SLA with concrete stages.
    assert "Acknowledge receipt" in text
    assert "Critical/High" in text
    # Coordinated disclosure window.
    assert "90 days" in text
    # Private reporting, not the public tracker.
    assert "Do not open a public issue" in text


def test_governance_defines_release_and_escalation() -> None:
    text = (ROOT / "docs" / "governance.md").read_text()
    assert "Release & deprecation policy" in text
    assert "Semantic Versioning" in text
    assert "X-Sovereign-API-Version" in text  # API lifecycle wired to real code
    assert "Escalation path" in text
    assert "Ownership model" in text
    assert "SECURITY.md" in text  # links the security response
