# RA — Risk Assessment

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **RA-2** Security Categorization | implemented | See [`../system-description.md`](../system-description.md) §"Categorisation (FIPS 199)". Overall impact: Moderate. |  |
| **RA-3** Risk Assessment | organizational | Agency risk assessment process; informed by the chassis POA&M and the continuous-monitor history. | [`docs/ssp/poam.md`](../poam.md) |
| **RA-5** Vulnerability Monitoring and Scanning | implemented | The `trivy-scan` CI job scans every built container image for known CVEs and fails on critical/high. The continuous monitor (5.2) tracks scan freshness. Quarterly penetration testing is organizational. | `.github/workflows/ci.yml::trivy-scan` |
| **RA-5(2)** Update Vulnerabilities to Be Scanned | implemented | Trivy auto-updates its CVE DB on each invocation. The CI job pins the trivy version (not :latest) so a DB schema break is a tracked change. |  |
| **RA-7** Risk Response | implemented (via POA&M) | All identified risks land in [`docs/ssp/poam.md`](../poam.md) with a remediation owner and target date. |  |
