# STIG Hardening Checklist

> Phase 5 task 5.4 of the roadmap. Documents the chassis-side hardening
> applied to every container image, plus the controls left to the
> hosting environment.

The chassis ships ten distinct container images: the four Python
services (broker, control-plane, audit-service, metering-service), the
portal (multi-stage nginx), and external dependencies pulled by tag
(OPA, ClickHouse, MinIO, DynamoDB Local). Hardening rules are applied
to the in-repo images; external dependencies inherit their vendor's
posture and are flagged by the trivy CI job (Phase 5.2) if a CVE is
published.

## Chassis-side hardening (applied)

Every chassis image satisfies the following:

| # | Requirement | How / Evidence |
| --- | --- | --- |
| 1 | Pinned base image tag (no `:latest`) | `python:3.11.10-slim-bookworm`, `nginx:1.30.3-alpine`, `node:22.13.0-alpine`, `openpolicyagent/opa:1.6.0-rootless` (compose). |
| 2 | Non-root runtime user | Each Python image creates `sovereign:1000` and `USER sovereign:sovereign` before CMD. The portal image runs as the upstream nginx image's `nginx` user. |
| 3 | OCI provenance labels | `org.opencontainers.image.{title,description,source,licenses,vendor}` set on every chassis image so the registry surfaces them. |
| 4 | HEALTHCHECK | Every chassis service image declares a HEALTHCHECK that hits `/healthz`. The orchestrator restarts a container that fails the check. |
| 5 | Vulnerability scan gate | The CI `docker-build` matrix runs `aquasecurity/trivy-action@0.28.0` against every built image after build; the job fails on any critical/high CVE. |
| 6 | No build-time secrets | Build args carry only public configuration (`VITE_BROKER_URL` etc.). Secrets (DEV_BEARER_TOKEN, BROKER_PASSWORD, AWS creds) come from env vars at runtime, never baked into layers. |
| 7 | Python bytecode disabled + unbuffered stdout | `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1` on every Python image. |
| 8 | Site-packages owned by root, app code by service user | `pip install` runs as root; `chown -R sovereign:sovereign /app` runs after install, so the runtime user can read but not modify Python modules. |
| 9 | nginx runs on an unprivileged port | The portal nginx config is sed-rewritten from `:80` to `:8080` so the unprivileged `nginx` user can bind it. Host published as :8088. |
| 10 | Response-header hardening | `nginx.conf` sets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`. |
| 11 | Image signing and provenance verification | The Docker CI job signs images with keyless cosign and uploads GitHub build provenance; `deploy/k8s/admission-cosign-policy.yaml` verifies keyless signatures, digest pinning, and SLSA provenance before admission. |

## Chassis-side hardening (POA&M open items)

| Item | Severity | Tracking |
| --- | --- | --- |
| Switch the Python base from Debian to a FIPS-validated Python build | Medium | POA&M 5.4-A in [`ssp/poam.md`](./ssp/poam.md) |
| Remove inherited CVE allow-list entries once fixed packages are available in the pinned base images | Medium | POA&M 5.4-CVE-* in [`ssp/poam.md`](./ssp/poam.md) |
| Switch ClickHouse / MinIO base images to STIG-hardened distros | Medium | Tracked in agency IaC; out of scope for this repo |

## Inherited from the hosting environment

The following STIG-level controls are not implemented in this repo
because they sit below the container boundary:

- Kernel hardening (sysctl, lockdown, IMA) — provided by the container
  host (EKS/AKS worker node AMI hardening, or the on-prem hardened
  Linux build).
- Filesystem permissions on host paths — `/var/lib/docker`, etc. —
  inherited.
- Audit subsystem (auditd / sysmon) — runs on the host, not the
  container.
- Network namespace isolation — provided by the container runtime.
- AppArmor / SELinux profiles — applied by the agency-managed
  container runtime configuration.

The agency operations team documents the per-environment STIG checklist
inside their own IaC; the chassis ships its slice of the surface here.

## Running the hardening verification

```
# Build every chassis image locally
make up
docker compose build

# Verify every chassis image runs as a non-root user
for svc in broker control-plane audit-service metering-service portal; do
  img=$(docker compose images --quiet $svc)
  echo "$svc → user=$(docker inspect --format '{{.Config.User}}' $img)"
done
# Expected (no entry is 'root' / '0'):
#   broker          → user=sovereign:sovereign
#   control-plane   → user=sovereign:sovereign
#   audit-service   → user=sovereign:sovereign
#   metering-service→ user=sovereign:sovereign
#   portal          → user=nginx

# Verify OCI labels round-trip
for svc in broker control-plane audit-service metering-service portal; do
  img=$(docker compose images --quiet $svc)
  docker inspect --format '{{.Config.Labels}}' $img \
    | jq -r '."org.opencontainers.image.title"'
done

# Run trivy locally for any image (CI does this on every build)
trivy image --severity CRITICAL,HIGH \
  ghcr.io/bobcatsfan33/sovereign-platform-broker:latest
```
