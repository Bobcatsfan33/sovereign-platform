# example-pack — SSP Addendum (worked example)

> Phase 5 task 5.7 validation. This is a worked example of the
> [`pack-addendum-template.md`](../pack-addendum-template.md). It
> documents a hypothetical "example-pack" used to prove the chassis's
> pack-extension mechanism end-to-end. Real packs (AI Pack, Data Pack,
> etc.) ship their own addenda in this directory.

| Field | Value |
| --- | --- |
| Pack id | `example-pack` |
| Pack version | `0.1.0` |
| Authorisation owner | Sovereign Platform Team, platform@example.gov |
| Last review date | 2026-05-24 |

## 1 — Pack scope

`example-pack` adds a single managed-cache service type that the
chassis renders into an Envoy + Redis sidecar configuration. It
introduces no new external egress beyond what the base chassis already
allows: the cache lives inside the agency VPC and the broker writes
its config to the same S3 bucket as every other rendered artefact.

The pack exists to **validate the chassis's pack-extension contract**
end-to-end:

- Its renderer extends `BaseRenderer` (Phase 1.1).
- Its catalogue entry extends `CatalogStore` (Phase 1.7).
- It ships a `policies/` bundle in package `sovereign.pack.example_pack`
  that the top-level decision aggregates correctly (Phase 2.5).
- It registers itself via `pack.toml` entry-point discovery (Phase 1.9).
- This addendum demonstrates the SSP addendum merge (Phase 5.7).

## 2 — New service types

| Service type | Plans | Bindable | Compliance controls auto-satisfied |
| --- | --- | --- | --- |
| `managed-cache` | `tiny-1gb`, `small-4gb` | yes | AC-3 (RBAC inherited), SC-8 (TLS required), SC-28 (encryption_at_rest), CM-7 (tenant-allowed) |

## 3 — New components

| Component | Role | Boundary | Network egress |
| --- | --- | --- | --- |
| `redis-sidecar` | Per-instance Redis container co-located with Envoy on the same host | in (inside boundary) | none (loopback to Envoy only) |
| `cache-metrics-exporter` | Prometheus exporter for the Redis sidecar | in | metrics scrape from agency Prometheus inside VPC |

## 4 — Pack-specific OPA policies

| Rule (package) | Control | Deny reasons |
| --- | --- | --- |
| `sovereign.pack.example_pack.persistence` | SC-28 | "example-pack/SC-28: AOF persistence must be enabled on storage-backed cache plans" |
| `sovereign.pack.example_pack.tls` | SC-8 | "example-pack/SC-8: cache must require TLS on the client side" |

Tests live at `packs/example-pack/policies/tests/`. The CI `policy-test`
job runs `opa test packs/example-pack/policies/` alongside the base
bundle when the pack is installed.

## 5 — Pack-specific data flows

| # | From | To | Protocol | Port | Direction | Auth | Encryption-in-transit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ex-1 | Envoy sidecar | Redis sidecar | Redis-TLS | 6380 | loopback | password + TLS | TLS 1.3 |
| ex-2 | Agency Prometheus | cache-metrics-exporter | HTTPS | 9121 | inbound (scrape) | mTLS | TLS 1.3 |

No new boundary crossings vs the base SSP.

## 6 — Pack-specific control mapping

### AC

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| AC-3 | inherited from base | `_enforce_rbac` already gates `provision` action on the chassis-side. | `apps/broker/app/main.py` |

### SC

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| SC-8 | implemented (pack rule) | `sovereign.pack.example_pack.tls` rejects any plan that doesn't set `tls: true`. | `packs/example-pack/policies/tls.rego` |
| SC-28 | implemented (pack rule) | `sovereign.pack.example_pack.persistence` rejects storage-backed plans without AOF persistence. | `packs/example-pack/policies/persistence.rego` |

### CM

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| CM-2 | inherited from base | Rendered Redis + Envoy bootstrap stored in the same versioned S3 path as every other instance. | `apps/control-plane/app/main.py::render` |

## 7 — Pack-specific POA&M items

| ID | Severity | Title | Source | Owner | Target | Status |
| --- | --- | --- | --- | --- | --- | --- |
| pack:example-pack:1 | Low | Wire `cache-metrics-exporter` mTLS roots into agency Prometheus IaC sample | SC-8 in agency IaC | Platform Ops | 2026-Q4 | open |

## 8 — Pack-specific incident response

No pack-specific scenarios. The base [`../../incident-response.md`](../../incident-response.md)
covers cache compromise as a tenant-resource incident (§3.1).

## 9 — Pack installation acceptance checklist

- [x] `opa test packs/example-pack/policies/` passes at 100% coverage.
- [x] `managed-cache` appears under the Example Pack section in the
      portal catalogue.
- [x] `redis-sidecar` image passes trivy at the chassis gate.
- [x] Data-flow rows above match the agency egress allow-list.
- [x] Pack-specific POA&M item accepted.

This addendum **validates** the chassis's Phase 5.7 pack-SSP-extension
contract. Real production packs use the same template; this
example-pack exists only as the contract test.
