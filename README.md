# Sovereign Platform

A compliance-native self-service infrastructure platform for regulated and government environments. Sovereign Platform ships as a **base chassis** plus modular **service packs** (AI, Developer Platform, Data, SecOps, Identity, Edge, Multi-Cloud, Comms, Blockchain, FinOps).

> **North star**: any team inside a government agency can provision compliant infrastructure in minutes, not weeks. Every resource is born hardened, auditable, and policy-checked. The platform is the single control plane for all infrastructure.

The base chassis grew out of a clean-room Open Service Broker implementation — Envoy control plane, OSB lifecycle, dynamic templates, Packer/SaltStack image automation, multi-region load-balancer deployment, sidecar support, and operational auditability. Governance services (dedicated audit pipeline, metering, policy decision models) were merged in from the sovereign-ai-broker prototype during Phase 0 of the product roadmap.

> This repository does not contain proprietary code, diagrams, or confidential implementation details from any third party. It implements common cloud/platform-engineering patterns from public summaries and fills missing pieces with standard engineering design.

## Base chassis services

| Service | Port | Purpose |
| --- | --- | --- |
| `broker` | 8080 | OSB v2 API — catalog, provision, bind, update, deprovision, last_operation. HTTP Basic per spec. |
| `control-plane` | 8090 | Renders Envoy v3 configs and persists them to S3. Bearer auth. |
| `audit-service` | 8086 | Single ingestion point for `AuditEvent`s. ClickHouse-backed, in-process buffer for graceful degradation. Bearer auth. |
| `metering-service` | 8087 | DynamoDB-backed `Usage` records. Tenant-scoped query API. Bearer auth. |

Each service exposes `/healthz` unauthenticated for compose / K8s probes.

## Local quick start

Requires Docker (with `compose`), Python 3.11+, and `make`.

```bash
cp .env.example .env

# bring up the whole stack (compose builds the four service images,
# then runs them alongside DynamoDB Local, MinIO, and ClickHouse)
make up                         # foreground
make up-detached                # background

# in another shell — sanity check and seed
make status                     # docker compose ps + curl /healthz of each service
make seed                       # post a couple of demo provisioning requests
make logs                       # tail -f all logs
make down                       # stop the stack (keeps volumes)
make clean                      # stop + wipe volumes
```

Useful URLs once `make up` is healthy:

- Broker:          <http://localhost:8080/v2/catalog>
- Control plane:   <http://localhost:8090/healthz>
- Audit service:   <http://localhost:8086/healthz>
- Metering:        <http://localhost:8087/healthz>
- MinIO console:   <http://localhost:9001>  (user/pass: `minioadmin` / `minioadmin`)
- ClickHouse HTTP: <http://localhost:8123>

## Provisioning by hand

```bash
curl -u broker:broker -X PUT http://localhost:8080/v2/service_instances/demo-lb \
  -H 'Content-Type: application/json' \
  -d '{
    "service_id":"sovereign-envoy-lb",
    "plan_id":"standard-regional",
    "organization_guid":"demo-org",
    "space_guid":"demo-space",
    "parameters":{
      "region":"us-east-1",
      "listeners":[{"name":"http","port":8088,"protocol":"HTTP"}],
      "routes":[{"host":"app.local","prefix":"/","cluster":"app"}],
      "clusters":[{"name":"app","endpoints":["host.docker.internal:3000"]}]
    }
  }'
```

## Development workflow

```bash
make install      # create .venv (Python 3.11), install project + dev extras
make test         # pytest -q
make test-cov     # pytest with coverage, fails under 80%
make lint         # ruff check libs apps tests
make typecheck    # mypy libs/common/sovereign
make check        # lint + typecheck + test — the local equivalent of CI
make fmt          # ruff --fix
make smoke        # bring stack up, hit it with the demo provisioner, leave it running
```

CI runs the same four steps in `.github/workflows/ci.yml` and additionally builds the four service Docker images on every PR, pushing them to GHCR on merge to `main`.

## Repository layout

```text
apps/broker             Open Service Broker (HTTP Basic, OSB v2)
apps/control-plane      Envoy v3 config renderer (Bearer)
apps/audit-service      Dedicated audit ingestion (Bearer, ClickHouse)
apps/metering-service   Dedicated metering store (Bearer, DynamoDB)
libs/common/sovereign   Shared library — models, store, audit client,
                        envoy_v3 validator, settings, security, errors
infra/terraform         AWS modules
infra/packer            Envoy AMI image definition
infra/salt              Salt states for Envoy hosts
deploy/k8s              Kubernetes manifests
docs                    Architecture, gap analysis, runbooks
tests                   Pytest suite (unit + integration)
scripts                 Local helpers (e.g. provision-demo.sh)
```

## Core design

A team requests a managed L7 load balancer through the broker. The broker authenticates the call (HTTP Basic per OSB spec), validates the request body against the Pydantic schema, persists desired state to DynamoDB, asks the control plane to render an Envoy v3 snapshot (which is itself schema-validated before being written), and emits an audit event to the dedicated audit service. The control plane stores the immutable snapshot in S3 (MinIO locally) and exposes the latest desired config to Envoy hosts.

The audit service decouples upstream services from ClickHouse availability: services emit best-effort, the service handles buffering and persistence. The metering service mirrors the same pattern for `Usage` records on DynamoDB and becomes the data layer for the quota and chargeback system in Phase 3 of the roadmap.

In production, Envoy hosts boot from Packer-built AMIs configured by SaltStack, retrieve their assigned snapshot, and run as regional or multi-region capacity pools.

## Auth model

| Surface | Scheme | Why |
| --- | --- | --- |
| Broker `/v2/*` | HTTP Basic | OSB v2 spec compliance (Cloud Foundry style). |
| Broker outbound to control-plane / audit | Bearer | Single shared token from `DEV_BEARER_TOKEN`. |
| Control plane, audit, metering | Bearer | `sovereign.security.require_bearer` shared dependency. |
| `/healthz` on every service | none | Allow compose / K8s liveness probes. |

In production, `DEV_BEARER_TOKEN`, `BROKER_PASSWORD`, and `S3_SECRET_KEY` are provisioned by the secret manager. Settings logs an ERROR at startup if `ENV=production` and any sentinel default is still in place.

## Errors

Every service emits RFC 7807-style JSON problem detail on error:

```json
{
  "type": "about:blank",
  "title": "not found",
  "status": 404,
  "detail": "instance not found",
  "service": "broker"
}
```

Downstream failures (DynamoDB, ClickHouse, S3, control-plane) translate to `503 service unavailable` with a descriptive detail rather than a stacktrace 500. Audit emission is best-effort and never blocks an upstream request.

## Production gaps intentionally filled

- Idempotent OSB lifecycle behaviour (provision/deprovision are idempotent; 410 Gone on deprovision-missing per spec).
- Validated schemas and safe defaults — Pydantic on the OSB API surface and on the rendered Envoy v3 config before S3 upload.
- Immutable, versioned config artifacts.
- Audit / event history via the dedicated service.
- Tenant-scoped metering as the data layer for chargeback.
- Health/readiness endpoints.
- Local development path (`make up && make seed && make test`).
- Infrastructure-as-code modules (Terraform).
- CI with lint, type check, coverage gate, multi-service Docker build.
- Security hardening — bearer auth across internal services, env-driven secrets, production safety check.
- Structured errors (RFC 7807) across every endpoint.

See `docs/architecture.md` and `docs/gap-analysis.md`.
