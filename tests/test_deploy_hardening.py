"""Static checks for production deployment artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _k8s_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in sorted((ROOT / "deploy" / "k8s").glob("*.yaml")):
        docs.extend(d for d in yaml.safe_load_all(path.read_text()) if d)
    return docs


def test_k8s_manifests_parse_and_cover_chassis_services() -> None:
    docs = _k8s_docs()
    deployments = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "Deployment"}
    assert {
        "broker",
        "control-plane",
        "audit-service",
        "metering-service",
        "portal",
        "opa",
    }.issubset(deployments)


def test_k8s_deployments_are_hardened() -> None:
    for doc in _k8s_docs():
        if doc.get("kind") != "Deployment":
            continue
        pod_spec = doc["spec"]["template"]["spec"]
        assert pod_spec["serviceAccountName"]
        assert pod_spec["automountServiceAccountToken"] is False
        assert pod_spec["securityContext"]["runAsNonRoot"] is True
        assert pod_spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for container in pod_spec["containers"]:
            assert ":latest" not in container["image"]
            assert "resources" in container
            assert "readinessProbe" in container
            assert "livenessProbe" in container
            security_context = container["securityContext"]
            assert security_context["allowPrivilegeEscalation"] is False
            assert "ALL" in security_context["capabilities"]["drop"]


def test_k8s_network_policy_default_deny_exists() -> None:
    policies = [d for d in _k8s_docs() if d.get("kind") == "NetworkPolicy"]
    assert any(p["metadata"]["name"] == "default-deny" for p in policies)


def test_k8s_config_exposes_audit_retention_days() -> None:
    config_maps = [d for d in _k8s_docs() if d.get("kind") == "ConfigMap"]
    config = next(c for c in config_maps if c["metadata"]["name"] == "sovereign-config")
    assert config["data"]["AUDIT_RETENTION_DAYS"] == "730"


def test_terraform_hardening_controls_present() -> None:
    terraform = "\n".join(
        p.read_text() for p in sorted((ROOT / "infra" / "terraform").rglob("*.tf"))
    )
    assert "aws_s3_bucket_public_access_block" in terraform
    assert 'sse_algorithm     = "aws:kms"' in terraform
    assert "point_in_time_recovery { enabled = true }" in terraform
    assert "deletion_protection_enabled = true" in terraform
    assert 'http_tokens   = "required"' in terraform
    asg = (ROOT / "infra" / "terraform" / "modules" / "asg" / "main.tf").read_text()
    assert 'ingress { from_port = 80 to_port = 8443 protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }' not in asg
