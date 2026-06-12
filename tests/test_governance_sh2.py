"""SH-2: engineering governance artifacts are present and cover the
security-sensitive paths (kept honest by a test)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_codeowners_covers_sensitive_paths() -> None:
    text = (ROOT / "CODEOWNERS").read_text()
    for path in (
        "/libs/common/sovereign/security.py",
        "/libs/common/sovereign/idp/",
        "/policies/",
        "/infra/",
        "/.github/",
    ):
        assert path in text, f"CODEOWNERS missing {path}"


def test_protect_script_enforces_review_and_signing() -> None:
    text = (ROOT / "scripts" / "org" / "protect.sh").read_text()
    assert "required_pull_request_reviews" in text
    assert "require_code_owner_reviews" in text
    assert '"required_signatures": true' in text
    assert '"allow_force_pushes": false' in text
    # Documents the single-owner caveat so it isn't enabled prematurely.
    assert "second maintainer" in text


def test_sdlc_policy_documents_gates() -> None:
    text = (ROOT / "docs" / "SDLC-POLICY.md").read_text()
    assert "AI-assisted" in text
    assert "CodeQL" in text
    assert "CODEOWNERS" in text
    assert "branch protection" in text.lower()
