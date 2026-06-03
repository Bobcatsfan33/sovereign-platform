"""CI supply-chain control regression tests."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _ci() -> dict:
    with (ROOT / ".github" / "workflows" / "ci.yml").open() as fh:
        return yaml.safe_load(fh)


def test_docker_job_has_keyless_signing_permissions() -> None:
    job = _ci()["jobs"]["docker-build"]
    permissions = job["permissions"]

    assert permissions["packages"] == "write"
    assert permissions["id-token"] == "write"
    assert permissions["attestations"] == "write"


def test_docker_job_signs_and_attests_published_images() -> None:
    steps = _ci()["jobs"]["docker-build"]["steps"]
    names = {step.get("name") for step in steps}
    uses = {step.get("uses") for step in steps}

    assert "install cosign" in names
    assert "sign image with keyless cosign" in names
    assert "actions/attest-build-provenance@v2" in uses


def test_docker_job_scans_before_push_and_sign() -> None:
    steps = _ci()["jobs"]["docker-build"]["steps"]
    names = [step.get("name") for step in steps]

    assert names.index("trivy scan (fail on critical/high)") < names.index("push scanned image")
    assert names.index("push scanned image") < names.index("sign image with keyless cosign")


def test_docker_job_does_not_publish_latest_tag() -> None:
    steps = _ci()["jobs"]["docker-build"]["steps"]
    build_step = next(step for step in steps if step.get("id") == "build")
    tags = str(build_step["with"]["tags"])

    assert ":latest" not in tags
