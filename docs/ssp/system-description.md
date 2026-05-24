# System Description

## System name

**Sovereign Platform — base chassis** (v0.4+, Phase 0 through Phase 4
of the [product roadmap](../../README.md)).

## Purpose

The Sovereign Platform is a self-service provisioning platform for
regulated and government environments. It exposes the Open Service
Broker (OSB) v2 API and a web portal that lets authorised personnel
provision pre-hardened infrastructure (load balancers in v0.1; the
broader catalogue is extended by service packs) without writing
infrastructure code and without bypassing the chassis policy engine.

Every state-changing request passes through:

```
identity → RBAC → quota → policy → render → state → metering → audit
```

…before any resource is created. The platform is intended to be the
single control plane for infrastructure inside the agency's authorised
boundary.

## Categorisation (FIPS 199)

| Aspect | Impact | Rationale |
| --- | --- | --- |
| Confidentiality | Moderate | The chassis processes tenant identifiers, principal names, and policy decisions. It does NOT process the tenant's data plane. |
| Integrity | Moderate | Falsified policy decisions or audit records would let a non-compliant resource land. Strong integrity controls are required (see SC-12, AU-9, AU-10). |
| Availability | Moderate | Outage prevents new provisioning but does not affect running tenant workloads. |

The overall impact level is **Moderate**, mapped to the NIST 800-53
Rev 5 Moderate baseline. Agencies operating at High should apply the
High overlay called out at the bottom of each control chapter.

## Boundary

The authorisation boundary contains the four chassis services
(`broker`, `control-plane`, `audit-service`, `metering-service`), the
OPA policy engine, the catalogue & quota datastores (DynamoDB), the
config artefact store (S3), the audit datastore (ClickHouse), and the
portal SPA served by nginx.

See [`boundary-and-data-flow.md`](./boundary-and-data-flow.md) for the
diagram, the data flows, the ports and protocols, and the
encryption-in-transit / at-rest mapping.

## System components

| Component | Role | NIST mapping (primary) |
| --- | --- | --- |
| `broker` (FastAPI :8080) | OSB v2 API; runs the identity → RBAC → quota → policy → render pipeline | AC-3, AC-6, AU-2, AU-12, CM-7 |
| `control-plane` (FastAPI :8090) | Renders Envoy v3 configs; validates them against Pydantic schema before S3 write | CM-2, CM-6, SC-7 |
| `audit-service` (FastAPI :8086) | Single ingestion point for all `AuditEvent`s; ClickHouse-backed with graceful degradation | AU-2, AU-3, AU-4, AU-6, AU-9, AU-12 |
| `metering-service` (FastAPI :8087) | Tenant-scoped `Usage` records; data source for chargeback and quota enforcement | AU-12, CM-8 |
| `opa` (OPA :8181) | Evaluates `sovereign.decision` against the layered base/pack/tenant Rego bundle in `policies/` | AC-3, AC-4, AC-6, CM-7, SC-8, SC-13, SC-28 |
| `portal` (nginx :8088 → static SPA) | Self-service browse + provisioning wizard + compliance dashboard | AC-3 (UI gating), AC-12 (session), SI-10 (client-side input validation) |
| `DynamoDB` | Service catalogue, instance state, binding state, per-tenant quota state, role bindings | CM-2, AC-6 |
| `S3 / MinIO` | Immutable rendered Envoy config artefacts | CM-2(2), SC-28, AU-9 |
| `ClickHouse` | Append-only audit trail | AU-4, AU-9 |

## Personnel roles

| Role | Privileges | Mapped to |
| --- | --- | --- |
| Platform operator | Manages the chassis itself; deploys upgrades; reads global audit | superuser group in JWT `groups` claim |
| Tenant admin | Provisions resources inside one tenant; reads tenant-scoped audit | `tenant_admin:{tid}` group |
| Tenant member | Reads tenant catalogue + own instances | `tenant_member:{tid}` group |
| Auditor | Read-only access to audit trail across configured scope | `auditor:{scope}` group |
| Service account (Basic) | Programmatic OSB callers (CF-style); RBAC bypassed | OSB Basic credentials |

Roles are enforced by the Phase 3 `AuthzResolver` (`libs/common/
sovereign/tenancy/authz.py`) using JWT `tid` + `groups` claims. The
group-to-role mapping is configurable per tenant (Phase 3.5 group sync).

## Operational environment

The chassis runs in containerised form. Reference deployments:

- **Local dev**: docker-compose (the `make up` target). Not authorised
  for production data; used for development and the CI integration test
  matrix only.
- **AWS GovCloud (us-gov-west-1, us-gov-east-1)**: EKS, IAM, KMS, S3,
  DynamoDB, CloudWatch. Hosting controls inherited from FedRAMP-
  authorised AWS services.
- **Azure Government (usgovvirginia, usgovarizona)**: AKS, Azure AD,
  Key Vault, Blob, Cosmos. Hosting controls inherited from FedRAMP-
  authorised Azure services.

The OPA `gov_region` policy rejects provisioning into any non-GovCloud
region by default.
