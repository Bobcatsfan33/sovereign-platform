# Sovereign Platform

A compliance-native self-service infrastructure platform for regulated and government environments. Sovereign Platform ships as a **base chassis** plus modular **service packs** — all of which now live in `packs/`: AI, Data, SecOps, Identity, Multi-Cloud, Edge, Comms, Blockchain, and FinOps (the roadmap's Developer Platform capability is delivered through the AI and Data packs). See [Service packs](#service-packs) for the full catalog.

> **North star**: any team inside a government agency can provision compliant infrastructure in minutes, not weeks. Every resource is born hardened, auditable, and policy-checked. The platform is the single control plane for all infrastructure.

The base chassis grew out of a clean-room Open Service Broker implementation — Envoy control plane, OSB lifecycle, dynamic templates, Packer/SaltStack image automation, multi-region load-balancer deployment, sidecar support, and operational auditability. Governance services (dedicated audit pipeline, metering, policy decision models) were merged in from the sovereign-ai-broker prototype during Phase 0 of the product roadmap.

> This repository does not contain proprietary code, diagrams, or confidential implementation details from any third party. It implements common cloud/platform-engineering patterns from public summaries and fills missing pieces with standard engineering design.

## Base chassis services

| Service | Port | Purpose |
| --- | --- | --- |
| `broker` | 8080 | OSB v2 API — catalog, provision, bind, update, deprovision, last_operation, /v2/instances, /v2/policy/check. HTTP Basic + Bearer. |
| `control-plane` | 8090 | Renders Envoy v3 configs and persists them to S3. Bearer auth. |
| `audit-service` | 8086 | Single ingestion point for `AuditEvent`s. ClickHouse-backed, in-process buffer for graceful degradation. Bearer auth. |
| `metering-service` | 8087 | DynamoDB-backed `Usage` records. Tenant-scoped query API. Bearer auth. |
| `opa` | 8181 | Open Policy Agent — evaluates `sovereign.decision` against the layered base/pack/tenant Rego bundle in `policies/`. |
| `portal` | 8088 | Sovereign Portal — static React/TS SPA: catalog browse, provisioning wizard with policy pre-check, instance dashboard, compliance dashboard. Talks to broker + audit-service from the browser via CORS. |

Each service exposes `/healthz` unauthenticated for compose / K8s probes.

## Service packs

All ten roadmap packs ship in `packs/`. A pack is a pip-installable wheel
discovered through the `sovereign.packs` entry point — installing it into a
chassis venv registers its renderers, connectors, catalog entries, and OPA
policy bundle with no chassis code changes (`discover_packs()` walks the
entry-point group at startup). Each pack contributes one or more
**service types** to `/v2/catalog` and a layered `sovereign.pack.<name>`
Rego bundle (100% test coverage, gated in CI) mapped to NIST SP 800-53
controls.

Renderers are pure: they produce a `RenderedArtifact` whose
`deployment_manifest` is applied by a chassis **deployment executor**
(`k8s-apply` / `terraform-apply` / config-only) — packs ship no apply
logic of their own. Packs that emit policy **obligations** (PII redaction,
audit tagging, validator registration, …) have them enforced fail-closed
by the broker at provision time.

| Pack | Service types | Backend | Key NIST controls |
| --- | --- | --- | --- |
| **AI** (`packs/ai`) | `inference-endpoint`, `rag-workspace` | k8s-apply | AC-4, SC-8, SC-28, SI-12 |
| **Data** (`packs/data`) | `managed-database`, `vector-db` | terraform-apply | SC-28, CP-9, SI-12 |
| **SecOps** (`packs/secops`) | `siem-workspace`, `log-pipeline` | k8s-apply | AU-9, AU-10, AU-11, SI-4 |
| **Identity** (`packs/identity`) | `idp-broker`, `scim-bridge` | config-only | IA-2, IA-2(1), IA-2(12), IA-4, IA-8 |
| **Multi-Cloud** (`packs/multicloud`) | `cloud-account`, `landing-zone` | terraform-apply | AC-4, CM-2, SC-7, AU-2 |
| **Edge** (`packs/edge`) | `edge-node`, `edge-cluster` | k8s-apply | SI-7, SI-7(9), SC-28, SR-11 |
| **Comms** (`packs/comms`) | `secure-email`, `secure-chat` | config-only | SC-8, SC-13, AU-11, AC-4 |
| **Blockchain** (`packs/blockchain`) | `permissioned-ledger` | k8s-apply | AC-3, IA-3, SC-12, SC-13 |
| **FinOps** (`packs/finops`) | `budget`, `chargeback-report` | metering (no infra) | SA-2, PM-3, AU-6 |
| **Developer Platform** | folded into AI/Data (container & data services) | — | — |

> The Developer Platform capability from the roadmap is delivered through
> the AI and Data packs' container/data service types rather than a
> separate pack. The other nine packs are independent wheels under
> `packs/`.

Install a pack into a running chassis venv:

```bash
pip install -e packs/ai          # registers inference-endpoint + rag-workspace
# the broker picks up the new service types + policy bundle on next start
```

## Local quick start

Requires Docker (with `compose`), Python 3.11+, and `make`.

> **Interpreter:** the project requires **Python 3.11–3.13** (3.14 also works). `make` auto-detects `python3.13/3.12/3.11`; if only an older `python3` is on PATH the `venv` target fails fast with guidance. Override with `make PYTHON=/path/to/python3.12 install`. If you use [`uv`](https://docs.astral.sh/uv/): `uv venv --python 3.12 && uv pip install -e ".[dev]"`.

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
make install      # create .venv (auto-detected Python 3.11–3.13), install project + dev extras
make test         # pytest -q (chassis + all packs/*/tests)
make test-cov     # pytest with coverage, fails under 80%
make lint         # ruff check libs apps tests packs
make typecheck    # mypy libs/common/sovereign
make check        # lint + typecheck + test — the local equivalent of CI
make fmt          # ruff check --fix (libs apps tests packs)
make smoke        # bring stack up, hit it with the demo provisioner, leave it running
```

`make check` mirrors CI. The `.github/workflows/ci.yml` pipeline additionally
runs the OPA policy gate over the base **and every pack bundle**, tests across a
Python 3.11/3.12/3.13 matrix, builds + lints the portal SPA, and builds the five
service Docker images (broker, control-plane, audit-service, metering-service,
portal) on every PR — Trivy-scanned, and pushed to GHCR on merge to `main`.

## Repository layout

```text
apps/broker             Open Service Broker (HTTP Basic, OSB v2)
apps/control-plane      Envoy v3 config renderer (Bearer)
apps/audit-service      Dedicated audit ingestion (Bearer, ClickHouse)
apps/metering-service   Dedicated metering store (Bearer, DynamoDB)
libs/common/sovereign   Shared library — models, store, audit client,
                        envoy_v3 validator, renderers, executors, secrets,
                        settings, security, errors
packs                   The ten service packs (AI, Data, SecOps, Identity,
                        Multi-Cloud, Edge, Comms, Blockchain, FinOps) — each
                        a wheel with renderers + OPA bundle + tests
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
| Broker `/v2/*` | HTTP Basic + Bearer JWT | OSB v2 compatibility plus tenant-aware authorization. |
| Service-to-service (broker→control-plane render/diff, audit & metering clients) | Workload identity and/or shared Bearer | `sovereign.security.service_auth_headers()` builds outbound auth symmetrically with the inbound check: it asserts this service's `WORKLOAD_IDENTITY` (default `spiffe://sovereign/<service>`) when workload identity is enabled, and includes `DEV_BEARER_TOKEN` only while `SHARED_BEARER_AUTH_ENABLED=true`. In the locked-down posture (workload identity on, shared bearer off) calls carry an identity header and **no shared token**. |
| Control plane, audit, metering (inbound) | Workload identity and/or shared Bearer | `sovereign.security.require_bearer` verifies the asserted workload identity against `ALLOWED_WORKLOAD_IDENTITIES`, and rejects traffic with 503 when shared bearer auth is disabled and no allowed identity is presented. |
| `/healthz` on every service | none | Allow compose / K8s liveness probes. |

In production, `DEV_BEARER_TOKEN`, `BROKER_PASSWORD`, and `S3_SECRET_KEY` are provisioned by the secret manager. The guardrails are **secure by default**: only an explicit development allowlist — `ENV` ∈ {`dev`, `development`, `local`, `test`, `testing`, `ci`} — tolerates the baked-in dev credentials. *Any* other value (`staging`, `demo`, `gov-prod`, or a typo) is treated as a managed environment, so a mislabelled deployment can never silently run on `minioadmin`/`dev-token`. Settings fail closed at startup whenever a managed environment still has a sentinel default in place, unless an operator explicitly sets `STRICT_SECRETS=false` for a temporary break-glass migration window. `BROKER_TRUST_BASIC_AUTH` also defaults to false in managed environments so OSB Basic callers do not skip RBAC by accident.

Managed-environment JWT auth requires `OIDC_ISSUER_URL` and `OIDC_AUDIENCE`; when configured, the broker verifies Bearer JWTs against the issuer JWKS instead of the local HS256 development secret.

Managed-environment secret material must come from a managed backend. Set
`SECRETS_PROVIDER=aws-secrets-manager` or `SECRETS_PROVIDER=aws-ssm`
with `SECRETS_PREFIX` for environment scoping; any non-development `ENV`
refuses to start with the env-only provider unless `REQUIRE_MANAGED_SECRETS=false`
is explicitly set for a temporary migration window.

When a managed provider is configured, the sensitive settings are **resolved
end-to-end** at startup: `get_settings()` fetches each one from the backend by
logical name (`service-bearer-token`, `broker-password`, `s3-access-key`,
`s3-secret-key`, `jwt-signing-secret`, `audit-signing-private-key`,
`siem-webhook-token`, each under `SECRETS_PREFIX`) and overrides the env/dev
value, so every service runs on the real secret rather than a baked-in default.
A secret absent from the backend is left untouched and the sentinel gate then
fails closed. The `env` provider path does no backend calls, keeping dev/CI
hermetic.

For service-to-service auth, production deployments should terminate mTLS
at a trusted mesh/front door and pass an allow-listed `X-SPIFFE-ID` or
`X-Sovereign-Workload-Identity` header to protected services. Set
`WORKLOAD_IDENTITY_ENABLED=true` and comma-separate allowed identities in
`ALLOWED_WORKLOAD_IDENTITIES`.

`WORKLOAD_IDENTITY_ENABLED` trusts the identity header directly, which is
only safe when the service is unreachable except through the mesh. The
hardened posture sets **`MTLS_REQUIRED=true`** (default on for any non-dev
`ENV`): the inbound side then trusts *only* the peer identity the mesh
verified via mTLS and forwarded as `X-Forwarded-Client-Cert` (XFCC). Envoy
sanitises any client-supplied XFCC, so the identity cannot be spoofed on a
direct path; plain `X-SPIFFE-ID` / `X-Sovereign-Workload-Identity` headers
are ignored in this posture. The SPIFFE id is read from the leaf cert's
`URI` SAN and checked against `ALLOWED_WORKLOAD_IDENTITIES` (`*` allows any
verified peer). A request with no valid XFCC is rejected `401`; a verified
but un-allow-listed identity is rejected `403`. The mesh must be configured
to forward XFCC (Envoy: `forward_client_cert_details: sanitize_set` with the
`uri` SAN included).

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
