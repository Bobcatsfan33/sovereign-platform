# IR — Incident Response

The chassis-side procedures, escalation paths, and notification
templates live in [`../../incident-response.md`](../../incident-response.md).
This chapter maps the IR family controls to that document.

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **IR-1** Policy and Procedures | implemented | `docs/incident-response.md` documents the chassis incident classes (tenant resource compromise, platform-level compromise, data breach, service outage) and the response procedure for each. |  |
| **IR-2** Incident Response Training | organizational | Agency-conducted; chassis-specific scenarios use the runbook section of `docs/incident-response.md`. |  |
| **IR-3** Incident Response Testing | organizational | Tabletop exercises live in the agency operations programme. The chassis ships a deterministic local stack (`make smoke`) that the agency uses as the substrate for tabletop scenarios. | `Makefile::smoke` |
| **IR-4** Incident Handling | implemented | The audit trail provides the timeline reconstruction; the policy-engine deny log identifies attempted bypasses; the continuous monitor (5.2) detects the drift that often signals a compromise. The runbook walks an operator through each. | `docs/incident-response.md` §3 |
| **IR-5** Incident Monitoring | implemented | The continuous monitor pages on-call when audit gaps, policy drift, or state drift exceed agency-defined thresholds. ClickHouse aggregations in the portal Compliance dashboard surface anomalies (denies per principal, denies per service type). | `scripts/continuous-monitor.py`; `apps/portal/src/pages/Compliance.tsx` |
| **IR-6** Incident Reporting | implemented (notification template) | The runbook provides templates for US-CERT, agency SOC, and tenant notification. The chassis does not send these automatically — the on-call operator does. | `docs/incident-response.md` §5 |
| **IR-7** Incident Response Assistance | organizational | Agency SOC contact info in `docs/incident-response.md` §6. |  |
| **IR-8** Incident Response Plan | implemented | The plan itself. | `docs/incident-response.md` |

See [`../../incident-response.md`](../../incident-response.md) for the
full procedure.
