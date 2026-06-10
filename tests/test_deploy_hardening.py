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


def test_frontdoor_rate_limit_overlay_exists() -> None:
    ingresses = [d for d in _k8s_docs() if d.get("kind") == "Ingress"]
    ingress = next(i for i in ingresses if i["metadata"]["name"] == "sovereign-frontdoor")
    annotations = ingress["metadata"]["annotations"]

    assert annotations["nginx.ingress.kubernetes.io/force-ssl-redirect"] == "true"
    assert annotations["nginx.ingress.kubernetes.io/limit-rps"] == "10"
    assert annotations["nginx.ingress.kubernetes.io/limit-burst-multiplier"] == "3"
    assert annotations["nginx.ingress.kubernetes.io/limit-connections"] == "20"
    assert ingress["spec"]["tls"]


def test_cosign_admission_policy_exists() -> None:
    policies = [d for d in _k8s_docs() if d.get("kind") == "ClusterPolicy"]
    policy = next(p for p in policies if p["metadata"]["name"] == "verify-sovereign-platform-images")
    rule = policy["spec"]["rules"][0]
    verify = rule["verifyImages"][0]

    assert policy["spec"]["validationFailureAction"] == "Enforce"
    assert verify["required"] is True
    assert verify["verifyDigest"] is True
    assert verify["mutateDigest"] is True
    assert "ghcr.io/bobcatsfan33/sovereign-platform-broker:*" in verify["imageReferences"]
    attestor = verify["attestors"][0]["entries"][0]["keyless"]
    assert attestor["issuer"] == "https://token.actions.githubusercontent.com"
    assert "Bobcatsfan33/sovereign-platform" in attestor["subject"]
    assert verify["attestations"][0]["type"] == "https://slsa.dev/provenance/v1"


def test_backend_services_have_horizontal_autoscaling() -> None:
    """Each backend service scales with load (CPU-driven HPA), within sane
    bounds, targeting a real Deployment that carries resource requests."""
    docs = _k8s_docs()
    hpas = {
        d["metadata"]["name"]: d
        for d in docs
        if d.get("kind") == "HorizontalPodAutoscaler"
    }
    deployments = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "Deployment"}

    for service in ("broker", "control-plane", "audit-service", "metering-service"):
        hpa = hpas[service]
        spec = hpa["spec"]
        assert spec["scaleTargetRef"]["kind"] == "Deployment"
        assert spec["scaleTargetRef"]["name"] == service
        assert spec["minReplicas"] >= 2
        assert spec["maxReplicas"] > spec["minReplicas"]
        metric_names = {m["resource"]["name"] for m in spec["metrics"] if m["type"] == "Resource"}
        assert "cpu" in metric_names  # utilization-based HPA needs requests

        # The target Deployment must declare CPU requests for HPA to work.
        app = deployments[service]["spec"]["template"]["spec"]["containers"][0]
        assert "cpu" in app["resources"]["requests"]


def test_spire_control_plane_manifest_present() -> None:
    """SPIRE server (StatefulSet) + agent (DaemonSet) exist with the platform
    trust domain, and the agent serves the Workload API on the socket path
    the renderer's MESH_SDS_SOCKET_PATH default points at."""
    from sovereign.settings import Settings

    docs = _k8s_docs()
    kinds = {(d.get("kind"), d.get("metadata", {}).get("name")) for d in docs}
    assert ("StatefulSet", "spire-server") in kinds
    assert ("DaemonSet", "spire-agent") in kinds

    cfgs = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "ConfigMap"}
    server_conf = cfgs["spire-server"]["data"]["server.conf"]
    agent_conf = cfgs["spire-agent"]["data"]["agent.conf"]
    assert 'trust_domain = "sovereign-platform"' in server_conf
    assert 'trust_domain = "sovereign-platform"' in agent_conf

    socket_default = Settings.mesh_sds_socket_path
    assert f'socket_path = "{socket_default}"' in agent_conf

    # The agent must expose that socket dir on the host for workloads to mount.
    agent_ds = next(
        d for d in docs if d.get("kind") == "DaemonSet" and d["metadata"]["name"] == "spire-agent"
    )
    host_paths = [
        v["hostPath"]["path"]
        for v in agent_ds["spec"]["template"]["spec"]["volumes"]
        if "hostPath" in v
    ]
    assert "/run/spire/sockets" in host_paths


def test_spire_registration_covers_chassis_services() -> None:
    import json

    docs = _k8s_docs()
    cfgs = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "ConfigMap"}
    entries = json.loads(cfgs["spire-registration-entries"]["data"]["entries.json"])["entries"]
    ids = {e["spiffe_id"] for e in entries}
    assert {
        "spiffe://sovereign-platform/broker",
        "spiffe://sovereign-platform/control-plane",
        "spiffe://sovereign-platform/audit-service",
        "spiffe://sovereign-platform/metering-service",
    }.issubset(ids)
    for entry in entries:
        assert "k8s:ns:sovereign-platform" in entry["selectors"]


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
