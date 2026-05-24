# SI — System and Information Integrity

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **SI-2** Flaw Remediation | implemented | Container image vulnerabilities flagged by the `trivy` job in CI (5.2). The job fails the build on any critical/high finding so vulnerable images never reach `latest`. | `.github/workflows/ci.yml::trivy-scan` |
| **SI-2(2)** Automated Flaw Remediation Status | implemented | Trivy scan results upload as a CI artefact every run; the continuous monitor includes "all images scanned within window" in its dashboard. | `scripts/continuous-monitor.py::check_image_scan_freshness` |
| **SI-3** Malicious Code Protection | inherited | Endpoint protection runs on the agency-managed container host (organizational). |  |
| **SI-4** System Monitoring | implemented | The audit-service's GET /events API + portal Compliance dashboard provide real-time visibility into every chassis action. The continuous monitor (5.2) drives automated alerts. | `apps/portal/src/pages/Compliance.tsx`; `scripts/continuous-monitor.py` |
| **SI-4(5)** System-Generated Alerts | implemented (CI integration) | The continuous monitor's exit code drives the CI cron's pass/fail status; a failed run notifies via the configured GitHub Actions integration (Slack, PagerDuty — agency-configured). | `.github/workflows/ci.yml::continuous-monitor` |
| **SI-5** Security Alerts, Advisories, and Directives | organizational | Agency receives + triages CISA advisories. Chassis CVE response uses the trivy job + the standing PR workflow. |  |
| **SI-7** Software, Firmware, and Information Integrity | implemented (in part) | Container images are content-addressable (digest-pinned). The OPA policy bundle is mounted read-only. Audit rows are append-only by API design (no DELETE endpoint). | `apps/*/Dockerfile`; `docker-compose.yml::opa::volumes` |
| **SI-10** Information Input Validation | implemented | Every API endpoint receives Pydantic-validated input; invalid bodies return 422 with structured error messages (RFC 7807). The Envoy rendered config is itself Pydantic-validated against the v3 subset before S3 write. | `libs/common/sovereign/models.py`; `libs/common/sovereign/envoy_v3.py`; `libs/common/sovereign/render.py` |
| **SI-11** Error Handling | implemented | `install_problem_detail_handlers` wraps every chassis service with RFC 7807 problem-detail responses. Stack traces never leak — the `detail` field is bounded to the exception message; the full traceback is logged at ERROR but never sent to the client. | `libs/common/sovereign/errors.py`; `tests/test_broker_errors.py` |
| **SI-12** Information Management and Retention | implemented (per AU-11) | Audit retention is the agency-configured ClickHouse TTL. Instance state is retained until the instance is deprovisioned. |  |

## High overlay

| Additional | Note |
| --- | --- |
| SI-7(1)+(6) Integrity Checks + Cryptographic Protection | Sign every container image with cosign and verify at admission (POA&M 5.2-H). |
| SI-4(2) Automated Tools and Mechanisms for Real-Time Analysis | Wire ClickHouse alerts to a SIEM (organizational). |
