# Observability, Audit Integrity, and Supply Chain

This sprint adds enterprise operating controls that can be validated before
the first production deployment.

## Runtime Metrics

Every Python service exposes unauthenticated Prometheus text metrics at
`/metrics`:

- `broker`
- `control-plane`
- `audit-service`
- `metering-service`

The common liveness metric is:

```text
sovereign_service_up{service="<service>"} 1
```

Services also expose local readiness gauges such as registered renderers,
registered executors, buffered audit events, spooled audit events, and whether
the metering table has been ensured.

## Audit Integrity

The audit service now hash-chains every accepted event:

- `previous_hash` points to the prior accepted event.
- `event_hash` is a SHA-256 digest of the canonical event payload.
- Existing ClickHouse tables are migrated with `ADD COLUMN IF NOT EXISTS`.
- Query responses include both fields so downstream SIEM, GRC, and evidence
  tools can verify continuity.

Accepted events are chained even when ClickHouse is unavailable and the event
falls back to the in-memory buffer or durable spool.

Audit rows can also carry an Ed25519 service signature:

- `signature_key_id` identifies the active audit-service key.
- `signature` signs the canonical event payload after hash chaining.
- `REQUIRE_AUDIT_SIGNING=true` makes startup fail when key material is absent.

Configure signing with:

```bash
AUDIT_SIGNATURE_KEY_ID=audit-service-2026q3
AUDIT_SIGNING_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
REQUIRE_AUDIT_SIGNING=true
```

## SIEM Export

Set `SIEM_WEBHOOK_URL` to export each accepted hash-chained audit event to a
SIEM or log collector. Set `SIEM_WEBHOOK_TOKEN` when the receiver expects
Bearer authentication. Export is best-effort; failed webhook delivery never
blocks the local audit trail.

Relevant settings:

- `SIEM_WEBHOOK_URL`
- `SIEM_WEBHOOK_TOKEN`
- `SIEM_WEBHOOK_TIMEOUT_SECONDS`

## Image Signing and Provenance

The GitHub Actions Docker job now publishes immutable `:${{ github.sha }}`
image tags only. On `main` pushes, each image is:

- built and scanned with Trivy,
- signed with keyless Sigstore/cosign,
- attested with GitHub build provenance,
- pushed to GHCR with registry-backed attestations.

Consumers should deploy by digest or immutable SHA tag and verify signature and
provenance before promotion.
