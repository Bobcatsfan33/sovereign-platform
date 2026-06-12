# Secure SDLC Policy

This one-page policy records the development workflow and its enforced gates —
the input to an SSDF (NIST SP 800-218) self-attestation. It documents how code
is written, reviewed, and verified, including AI-assisted development.

## Development model

Changes are made on short-lived branches and land on `main` only through pull
requests. Development is **AI-assisted**: an LLM agent proposes changes, but
every change is subject to the same automated gates and human review as any
other, with a named human accountable for each merge.

## Enforced gates (every PR)

| Gate | Mechanism |
| --- | --- |
| Lint + type check | `ruff`, `mypy` (CI `ci` workflow) |
| Tests (3.11–3.13) + coverage | `pytest` matrix |
| Policy unit tests | OPA `opa test` (100% coverage on bundles) |
| Dependency audit + SBOM | `pip-audit`, CycloneDX |
| Container scan | Trivy gate (HIGH/CRITICAL, fail-closed) |
| SAST | CodeQL (python, javascript) — `security` workflow |
| IaC SAST | `terraform validate` + `tfsec` (`terraform` job) |
| Supply-chain attestation | cosign keyless signing + SLSA v1 provenance (main) |
| Code-owner review | `CODEOWNERS` on auth / policy / infra / CI paths |

## Branch protection (SH-2)

`scripts/org/protect.sh` applies, as code: required PR, one approving review
that is not the author, required status checks, no force-push or deletion,
code-owner review, and signed commits. It is enabled the moment a **second
maintainer** is named (a single owner cannot satisfy not-the-author review).
Until then, continuity depends on one person — the single largest non-code
gap, tracked in `docs/governance.md`.

## Vulnerability response

Reported and handled per `SECURITY.md` (private channel, response SLA,
coordinated disclosure). Findings are triaged into the POA&M
(`docs/ssp/poam.md`).

## Evidence

The SSP control evidence (`scripts/ssp_validate.py`), the NIST→ISO crosswalk
(`scripts/crosswalk_validate.py`), and the continuous monitor
(`scripts/continuous_monitor.py`) provide the ongoing assurance an assessor
reviews against this policy.
