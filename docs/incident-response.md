# Sovereign Platform — Incident Response Plan

> Phase 5 task 5.3 of the roadmap. Documents the chassis-side
> procedures for the four incident classes the platform anticipates,
> the escalation paths, and the notification templates. Maps to NIST
> 800-53 Rev 5 IR family controls (see
> [`ssp/controls/ir.md`](./ssp/controls/ir.md)).

## 1 — Severity scale

The chassis uses the standard SOC severity scale; SEV-1 and SEV-2
trigger 24×7 on-call paging.

| Severity | Definition | Initial response | Escalation |
| --- | --- | --- | --- |
| SEV-1 | Confirmed compromise of the chassis itself (e.g. attacker-controlled image running in the boundary), confirmed data breach of audit / state, or platform-wide outage > 15 min. | Page primary + secondary on-call within 5 min; agency SOC within 15 min. | CISO + AO within 60 min. |
| SEV-2 | Single chassis component compromised but blast-radius contained, or platform-wide degradation (e.g. broker returns 5xx > 5% of requests) > 30 min. | Page primary on-call within 5 min; agency SOC within 30 min. | CISO if not resolved in 4 h. |
| SEV-3 | Single-tenant resource compromise, intermittent platform errors, or anomalous policy-deny spike. | Slack #sovereign-oncall within 30 min. | None unless escalated. |
| SEV-4 | Awareness only — CVE published against a chassis dependency, suspicious-but-blocked activity in audit logs. | Track in `docs/ssp/poam.md`. | None. |

## 2 — Incident classes

### 2.1 — Tenant resource compromise

A resource provisioned by the chassis (e.g. an Envoy LB) is
compromised. The compromise does NOT extend into the chassis itself.

**Detect via**: tenant-reported alert; anomalous traffic patterns; the
service pack's own monitoring.

**Respond**: §3.1.

### 2.2 — Platform-level compromise

The chassis itself (broker, control-plane, audit-service,
metering-service, opa, portal, or one of the datastores) is
compromised. Highest severity by default — escalates to SEV-1.

**Detect via**: trivy CVE scan, anomalous audit events (deny spike,
unexpected `actor` values), failed continuous-monitor run, agency SOC
alert.

**Respond**: §3.2.

### 2.3 — Data breach

Confirmed unauthorised access to chassis-managed data (audit trail,
policy decisions, instance state, tenant identifiers). SEV-1 by
default.

**Detect via**: agency SOC alert; ClickHouse access-log anomaly;
service-account credential leak detection.

**Respond**: §3.3.

### 2.4 — Service outage

The chassis is partially or fully unavailable but is not known to be
compromised. Severity scales with blast radius.

**Detect via**: continuous-monitor failure, paging from external
synthetic checks, agency NOC.

**Respond**: §3.4.

## 3 — Response procedures

### 3.1 — Tenant resource compromise

1. **Acknowledge** the alert in the paging system; assign incident
   commander (IC).
2. **Identify** the affected instance via the broker:
   `curl -u broker:broker http://broker:8080/v2/service_instances/<id>/last_operation`.
3. **Isolate** by deprovisioning the instance through the OSB API. The
   broker's `policy.evaluated` audit row will record the IC as the
   actor.
4. **Preserve evidence**: snapshot the Envoy config from S3
   (`aws s3 cp s3://sovereign-configs/instances/<id>/v<n>/envoy.yaml .`)
   before deprovisioning if the agency policy requires it.
5. **Notify** the affected tenant per §5.3 template within 24 h.
6. **Post-incident**: file a POA&M item if the compromise revealed a
   chassis gap; otherwise close.

### 3.2 — Platform-level compromise

1. **Acknowledge** + assign IC + paging tier escalation per §1.
2. **Contain**:
   - Rotate the shared chassis bearer token (`DEV_BEARER_TOKEN` env
     var) across every service.
   - Force-reload OPA from the trusted bundle path.
   - Block the suspect image at the registry; deploy the last
     known-good `sha`-tagged image.
3. **Eradicate**: identify the entry vector (CVE in dependency,
   misconfigured IAM, compromised admin credential). Patch and redeploy.
4. **Recover**:
   - Run `scripts/continuous-monitor.py --once` to verify policy +
     audit + state are consistent post-recovery.
   - Reconcile any DynamoDB↔S3 drift with manual operator review.
5. **Notify** per §5.1 (agency SOC + AO) within 60 min of acknowledgement;
   §5.2 (US-CERT) within agency-defined window.
6. **Post-mortem** within 5 business days; results into POA&M.

### 3.3 — Data breach

1. **Acknowledge** + escalate to CISO + AO immediately.
2. **Contain**:
   - Revoke any credentials known or suspected to be in the breach
     scope.
   - Disable the relevant audit-service / DynamoDB / S3 IAM principal.
   - Snapshot the entire audit trail at the time of containment
     (`SELECT * FROM sovereign.audit_events INTO OUTFILE ... FORMAT CSV`).
3. **Assess scope**: query the audit trail for the breach window;
   identify affected tenants and data classes.
4. **Notify**: §5.4 (data subjects, where required by agency privacy
   programme) within agency-mandated timeline.
5. **Post-incident**: agency privacy programme leads the breach-impact
   assessment; chassis team supports with evidence.

### 3.4 — Service outage

1. **Acknowledge** + IC.
2. **Diagnose**: `scripts/continuous-monitor.py --once`; check service
   `/healthz`; check upstream cloud platform status pages.
3. **Restore** by rolling back to the last known-good image
   (`docker pull ghcr.io/bobcatsfan33/sovereign-platform-<svc>:<prev-sha>`)
   or by scaling out the affected component.
4. **Notify** tenants per §5.5 if RTO is exceeded.
5. **Post-mortem** within 5 business days.

## 4 — Roles

| Role | Responsibility |
| --- | --- |
| Incident Commander (IC) | Owns the incident; runs the response; communicates status; calls all-clear. |
| Primary on-call | First responder per §1; identifies + contains. |
| Secondary on-call | Backup; covers IC if primary is unavailable. |
| Agency SOC | Investigates; coordinates with US-CERT; owns the agency-side notifications. |
| CISO | Approves containment actions that affect availability; speaks to leadership. |
| AO | Authorises continued operation post-recovery; signs the POA&M update. |

## 5 — Notification templates

### 5.1 — Agency SOC / AO (SEV-1/2)

> **Subject**: SEV-{1|2} Sovereign Platform incident — {short title}
>
> **What**: {one-line description, what's known}
>
> **When**: Detected {timestamp UTC}; acknowledged {timestamp UTC}.
>
> **Where**: {affected components: broker, control-plane, audit, ...}
>
> **Impact (preliminary)**: {who is affected, what data classes are in
> scope, RTO/RPO impact}.
>
> **Containment status**: {actions taken, what remains}.
>
> **Next update by**: {timestamp UTC}.
>
> **IC**: {name, contact}.

### 5.2 — US-CERT (per agency policy)

Use the agency-provided US-CERT template; chassis-specific evidence is
the audit trail extract and the continuous-monitor failure log.

### 5.3 — Tenant notification (tenant-resource compromise)

> **Subject**: Action required — your Sovereign Platform resource
> `{instance-id}` has been deprovisioned
>
> Our security monitoring detected suspicious activity targeting your
> Sovereign Platform resource `{instance-id}` ({service-type},
> provisioned {provisioned-date}). Per the platform's incident response
> procedure we have deprovisioned the affected resource to contain the
> compromise.
>
> What we know: {1-2 sentences, factual}.
>
> What we recommend: {re-provision a new resource, rotate any
> credentials shared with the compromised instance, review the
> tenant-side application's audit logs}.
>
> The rendered Envoy config snapshot at the time of the incident is
> preserved at `s3://sovereign-configs/incidents/{incident-id}/`. We
> can share it with your team upon request.
>
> Questions: {agency SOC contact, chassis team escalation}.

### 5.4 — Data subject notification (per agency privacy programme)

Use the agency privacy office's standard template. Chassis-specific
evidence is the audit trail extract covering the breach window.

### 5.5 — Tenant outage notification (SEV-2/3 outage)

> **Subject**: Sovereign Platform — partial outage {detected timestamp UTC}
>
> The Sovereign Platform broker is currently {fully | partially}
> unavailable. Existing provisioned resources are **{affected/unaffected}**;
> new provisioning is **{blocked/degraded}**.
>
> Estimated restore: {timestamp or "TBD; next update at HH:MM UTC"}.
>
> Status page: {agency status URL}.

## 6 — Contacts

Maintained by the agency operations programme; live copy in the
agency on-call runbook. The chassis team does not store individual
contact details in this repository.

- Primary on-call: agency PagerDuty service `sovereign-platform-primary`.
- Secondary on-call: agency PagerDuty service `sovereign-platform-secondary`.
- Agency SOC: per agency SOC runbook.
- CISO escalation: per agency leadership directory.
- AO: per ATO documentation.

## 7 — Post-incident

Every SEV-1 and SEV-2 incident produces:

1. A post-mortem document (template in `docs/templates/post-mortem.md`
   — TODO Phase 6) within 5 business days.
2. POA&M item(s) in [`ssp/poam.md`](./ssp/poam.md) for any newly
   discovered chassis gap.
3. A tabletop refinement to the relevant scenario in this document.
