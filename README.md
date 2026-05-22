# Sovereign Platform

A compliance-native self-service infrastructure platform for regulated and government environments. Sovereign Platform ships as a **base chassis** plus modular **service packs** (AI, Developer Platform, Data, SecOps, Identity, Edge, Multi-Cloud, Comms, Blockchain, FinOps).

> **North star**: any team inside a government agency can provision compliant infrastructure in minutes, not weeks. Every resource is born hardened, auditable, and policy-checked. The platform is the single control plane for all infrastructure.

The base chassis grew out of a clean-room Open Service Broker implementation — Envoy control plane, OSB lifecycle, dynamic templates, Packer/SaltStack image automation, multi-region load-balancer deployment, sidecar support, and operational auditability. Governance services (dedicated audit pipeline, metering, policy decision models) are being merged in from the sovereign-ai-broker prototype during Phase 0 of the [product roadmap](../../Documents/sovereign-platform-roadmap.md).

> This repository does not contain proprietary code, diagrams, or confidential implementation details from any third party. It implements common cloud/platform-engineering patterns from public summaries and fills missing pieces with standard engineering design.

## What this builds

- **Open Service Broker API** for self-service provisioning, binding, updating, and deprovisioning of load-balancer resources.
- **Envoy control plane** that generates validated Envoy bootstrap/config snapshots from templates.
- **DynamoDB-compatible state layer** for service instances, bindings, routes, and desired state.
- **S3-compatible config artifact publishing** for immutable Envoy snapshots.
- **ClickHouse audit/event stream** for operational history and platform observability.
- **Terraform modules** for AWS network, S3, DynamoDB, ALB, and ASG primitives.
- **Packer + SaltStack** AMI pattern for repeatable Envoy hosts.
- **Docker Compose local stack** for development.
- **Kubernetes manifests** for service deployment.
- **Tests** covering broker lifecycle and config rendering.

## Local quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Broker: http://localhost:8080/v2/catalog
- Control plane health: http://localhost:8090/healthz
- MinIO Console: http://localhost:9001
- ClickHouse: http://localhost:8123

## Example provision

```bash
curl -X PUT http://localhost:8080/v2/service_instances/demo-lb \
  -H 'Content-Type: application/json' \
  -d '{
    "service_id":"sovereign-envoy-lb",
    "plan_id":"standard-regional",
    "organization_guid":"demo-org",
    "space_guid":"demo-space",
    "parameters":{
      "region":"us-east-1",
      "listeners":[{"name":"https","port":8443,"protocol":"HTTP"}],
      "routes":[{"host":"app.local","prefix":"/","cluster":"app"}],
      "clusters":[{"name":"app","endpoints":["host.docker.internal:3000"]}]
    }
  }'
```

## Repository layout

```text
apps/broker          Open Service Broker API
apps/control-plane   Envoy config/control-plane API
libs/common          Shared models, store, config renderer, audit
infra/terraform      AWS modules and root examples
infra/packer         Envoy AMI image definition
infra/salt           Salt states for Envoy hosts
deploy/envoy         Local Envoy config/development assets
deploy/k8s           Kubernetes manifests
docs                 Architecture, gap analysis, runbooks
tests                Pytest suite
```

## Core design

Developers request a managed L7 load balancer through the broker. The broker validates the request, persists desired state, emits audit events, and asks the control plane to render an Envoy snapshot. The control plane stores immutable snapshots in S3-compatible object storage and exposes the latest desired config. In production, Envoy hosts boot from Packer-built AMIs configured by SaltStack, retrieve their assigned snapshot, and run as regional or multi-region capacity pools.

## Production gaps intentionally filled

The video-level architecture describes major components, but a production product also needs:

- Idempotent OSB lifecycle behavior
- Validated schemas and safe defaults
- Immutable config artifacts
- Rollback-ready versions
- Audit/event history
- Health/readiness endpoints
- Local development path
- Infrastructure-as-code modules
- CI tests and linting
- Security hardening hooks
- Multi-region extension points

See `docs/architecture.md` and `docs/gap-analysis.md`.
