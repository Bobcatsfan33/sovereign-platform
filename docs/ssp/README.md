# Sovereign Platform — System Security Plan (SSP) Scaffold

> Phase 5 (task 5.1, 5.5, 5.6, 5.7) deliverable of the Sovereign Platform
> roadmap. This directory is the authorization-package skeleton an
> assessor or AO would pick up to evaluate the base chassis against the
> **NIST 800-53 Rev 5 Moderate baseline**.

The chassis is the **System** under authorization. Service packs (AI,
Developer Platform, Data, etc.) extend the boundary; each pack ships
its own addendum that merges into this SSP via the template in
[`pack-addendum-template.md`](./pack-addendum-template.md).

## Layout

```
docs/ssp/
├── README.md                      this file — entry point
├── system-description.md          5.1 — narrative system characterisation
├── boundary-and-data-flow.md      5.5 — authorisation boundary + flows
├── poam.md                        5.6 — Plan of Action & Milestones
├── pack-addendum-template.md      5.7 — template for pack SSP addenda
├── pack-addenda/
│   └── example-pack.md            5.7 — worked example
└── controls/                      5.1 — per-family control implementations
    ├── README.md                  index of all 18 families + coverage matrix
    ├── ac.md                      AC — Access Control
    ├── au.md                      AU — Audit and Accountability
    ├── cm.md                      CM — Configuration Management
    ├── sc.md                      SC — System and Communications Protection
    ├── ia.md                      IA — Identification and Authentication
    ├── ir.md                      IR — Incident Response (→ docs/incident-response.md)
    ├── si.md                      SI — System and Information Integrity
    ├── ra.md                      RA — Risk Assessment
    ├── sa.md                      SA — System and Services Acquisition
    ├── cp.md                      CP — Contingency Planning
    ├── pe.md                      PE — Physical and Environmental Protection
    └── inherited.md               families fully inherited from the hosting environment (PE, MA, MP, AT, PS, PT, PM)
```

## How to read this SSP

Each control family chapter contains a **control mapping table** with one
row per applicable Moderate-baseline control:

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| AC-3 | implemented | Phase 3 RBAC via `AuthzResolver` | `libs/common/sovereign/tenancy/authz.py`; `tests/test_tenancy.py` |

Status values:

- **implemented** — the chassis enforces this control directly. The
  "Evidence" column cites the code path and the test that exercises it.
- **inherited** — the hosting environment (AWS GovCloud, Azure Gov,
  on-prem datacentre) provides this control. Listed in
  [`controls/inherited.md`](./controls/inherited.md).
- **organizational** — the operating agency owns the control (policy,
  procedure, training). Documented in the agency's SSP wrapper.
- **N/A** — the control does not apply to this system class. Justification
  documented inline.

## Continuous compliance evidence

This SSP is paired with the **continuous-monitoring** automation
(`scripts/continuous-monitor.py`, Phase 5 task 5.2). The monitor runs
on a CI cron and verifies — every hour — that:

1. The `sovereign.base.*` OPA policies still evaluate as expected
   (no rule drift).
2. Audit events from each chassis service are reaching ClickHouse
   inside the configured freshness window (no audit gaps).
3. Every ServiceInstance in DynamoDB has a corresponding rendered
   artifact in S3 (no state drift between control plane and broker).
4. Every published container image passes a `trivy` scan with zero
   critical/high CVEs.

A failed run pages on-call per
[`docs/incident-response.md`](../incident-response.md) §2.

## NIST 800-53 Rev 5 baseline

This document targets the **Moderate confidentiality, integrity, and
availability impact** baseline. The Sovereign Platform itself does not
process Controlled Unclassified Information (CUI) data — it provisions
infrastructure that may do so. Tenants run their own workloads inside
the resources the chassis hands them; data classification is asserted
through the OPA `context.classification` input attribute and enforced
by service-pack policies (AI Pack, Data Pack, etc. add the relevant
rules in their bundles).

A High-baseline overlay is straightforward when an agency requires it
(adds e.g. AC-2(11), SI-7(1)+(6), SC-8(2)); the changes are documented
inline in each control chapter under "High overlay".
