# CP — Contingency Planning

Most CP-family controls are **inherited** from the hosting cloud and
the agency's contingency plan. The chassis contributes the durability
of its own state.

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **CP-1** Policy and Procedures | organizational | Agency contingency plan covers the chassis. |  |
| **CP-2** Contingency Plan | organizational | Same. The chassis-specific RTO/RPO targets are in the agency contingency plan; the chassis state is in DynamoDB (Multi-AZ in GovCloud) and S3 (11 nines durability) so it survives single-AZ failure with zero data loss. |  |
| **CP-9** System Backup | inherited (DynamoDB PITR + S3 versioning) | DynamoDB Point-In-Time Recovery is enabled in the agency IaC; S3 versioning preserves prior rendered Envoy configs. The audit-service ClickHouse cluster is backed up nightly via the agency snapshot policy. | Agency IaC (organizational). |
| **CP-10** System Recovery and Reconstitution | implemented (continuous monitor reconciliation) | After a recovery, the continuous monitor (5.2) reconciles DynamoDB instance state against S3 rendered artefacts. Divergence is paged for manual remediation. | `scripts/continuous-monitor.py::check_state_drift` |
