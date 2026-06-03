# AU — Audit and Accountability

The chassis exposes the **dedicated audit service** as the single
ingestion point for every event. Inline ClickHouse writes were removed
in Phase 0 task 0.2 because they made every chassis service couple
to ClickHouse availability; the audit service now owns the connection
and buffers in-process when ClickHouse degrades so upstream callers
stay non-blocking.

Every event lands as a typed `AuditEvent` row:

```
ts | tenant_id | actor | action | resource | decision | metadata(JSON)
previous_hash | event_hash | signature_key_id | signature
```

…ordered by `(ts, tenant_id, action)` in the ClickHouse `MergeTree`
table. The metadata column carries the structured details (policy
denies, matched layers, plan id, etc.) so an investigator never has to
parse a free-text description.

## Control mapping

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **AU-2** Event Logging | implemented | Every state-changing OSB endpoint emits at least one `AuditEvent` (`instance.provisioned`, `instance.updated`, `binding.created`, `binding.deleted`, `instance.deprovisioned`). Every OPA evaluation emits `policy.evaluated` with the full decision (Phase 2 task 2.7). | `apps/broker/app/main.py::_evaluate_policy` and the lifecycle handlers; `tests/test_policy.py::test_provision_allowed_emits_allow_audit` |
| **AU-3** Content of Audit Records | implemented | Each record carries: timestamp (DateTime64(3)), actor, tenant_id, action, resource, decision, and a metadata JSON object. Policy events additionally include `denies: list[str]` and `matched_layers: list[str]`. | `libs/common/sovereign/models.py::AuditEvent`; `apps/audit-service/app/main.py::_row` |
| **AU-3(1)** Additional Audit Information | implemented | The metadata field is open-ended; service packs add their own keys (e.g. AI Pack adds `prompt_hash` for inference audits). The shape is documented in [`../system-description.md`](../system-description.md). |  |
| **AU-4** Audit Log Storage Capacity | implemented (ClickHouse + buffer) | ClickHouse storage is sized by the operating agency in their IaC (typical GovCloud deployment: 1 TB EBS gp3 per replica, retention 24 months — covers FedRAMP AU-11 requirement). The audit service in-process buffer is capped at 1000 events to bound memory loss during a ClickHouse outage. | `apps/audit-service/app/main.py::_BUFFER_CAP` |
| **AU-5** Response to Audit Logging Process Failures | implemented (graceful degradation) | When ClickHouse is unreachable, the audit service buffers the event in-memory and returns 202 to the caller; logs a WARNING line. When the buffer hits its cap the oldest event is dropped with an ERROR log. The continuous monitor (5.2) detects sustained buffer-drop and pages on-call. | `apps/audit-service/app/main.py::_flush_buffer`; `tests/test_audit_service.py::test_buffer_requeue_on_flush_failure` |
| **AU-6** Audit Record Review, Analysis, and Reporting | implemented | The portal Compliance dashboard (Phase 4 task 4.5) shows posture summary, recent policy violations, and a filterable audit log viewer. Filters: tenant_id, decision (allow/deny), action, resource, time window. | `apps/portal/src/pages/Compliance.tsx`; `apps/audit-service/app/main.py::query_events` |
| **AU-7** Audit Record Reduction and Report Generation | implemented | The audit-service GET /events endpoint supports parameterised filters that map directly to ClickHouse `WHERE` clauses; the portal aggregates client-side for the posture summary. | `apps/audit-service/app/main.py::query_events`; `apps/portal/src/pages/Compliance.tsx::summarise` |
| **AU-8** Time Stamps | implemented | `AuditEvent.ts` is timezone-aware (`datetime.now(UTC)`) and stored at millisecond resolution. The audit service column is `DateTime64(3)` (UTC). | `libs/common/sovereign/models.py::AuditEvent`; the ClickHouse `CREATE TABLE` in `apps/audit-service/app/main.py::_connect` |
| **AU-9** Protection of Audit Information | implemented (in part) | The audit service is the only component with ClickHouse write credentials. Bearer auth is enforced on POST /events. Audit row deletion is not permitted in the chassis schema (no DELETE issued). | `apps/audit-service/app/main.py`; `libs/common/sovereign/security.py::require_bearer`. The ClickHouse cluster itself enforces user-level access (organizational, agency IaC). |
| **AU-10** Non-repudiation | implemented | The audit service can sign every accepted row with an Ed25519 service-account key. Production defaults fail closed when audit signing is required but `AUDIT_SIGNATURE_KEY_ID` or `AUDIT_SIGNING_PRIVATE_KEY_PEM` is missing. | `libs/common/sovereign/audit_signing.py`; `apps/audit-service/app/main.py::_prepare_event`; `tests/test_audit_signing.py` |
| **AU-9(4)** Access by Subset of Privileged Users | implemented (RBAC) | Auditor read-access is gated by the `auditor:{scope}` group; the broker's `/v2/usage/{tenant_id}` enforces `ACTION_READ` and the portal Compliance page sends the JWT through to the audit service. | `apps/broker/app/main.py::get_usage`; `libs/common/sovereign/tenancy/authz.py` |
| **AU-11** Audit Record Retention | implemented (configurable) | Default retention is 24 months. The agency configures it via the ClickHouse `TTL` clause (added per-deployment in IaC, not in this repo — documented in POA&M 5.2-C). |  |
| **AU-12** Audit Record Generation | implemented | All chassis services emit via the shared `Audit` HTTP client. `Audit.emit()` always succeeds (best-effort) so a degraded audit service never blocks an OSB request — but the continuous monitor catches sustained failures within an hour. | `libs/common/sovereign/audit.py::Audit.emit`; `tests/test_audit_client.py` |

## High overlay

| Additional | Note |
| --- | --- |
| AU-10 Non-repudiation | Operational evidence must include key custody, rotation, and verifier procedures for the agency-managed signing key. |
| AU-9(3) Cryptographic Protection | KMS-encrypted ClickHouse EBS at-rest plus TLS to the cluster (inherited from agency IaC). |
