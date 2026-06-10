# Governance, Support, and Ownership

This is the operational contract an enterprise underwrites a platform against.
The **ownership decision itself** — a staffed internal platform team vs. a
vendor with an SLA — is a leadership decision this document cannot make
(WS6 of `docs/production-readiness.md`); what follows is the policy framework
that decision plugs into.

## Ownership model

> **Action required (not code):** name the owning team or vendor and fill in
> the on-call rotation and contacts. The bus-factor risk of a single-maintainer
> alpha is the largest non-code blocker and must be resolved deliberately.

| Role | Owner |
| --- | --- |
| Product owner | _TBD — named team or vendor_ |
| On-call / incident response | _TBD — rotation_ |
| Security response | _TBD — see SECURITY.md_ |

## Release & deprecation policy

- **Versioning:** Semantic Versioning; single source in
  `sovereign.version.__version__` (enforced by `tests/test_version.py`).
  Releases are cut by the tag-driven workflow (`docs/release.md`).
- **API lifecycle:** clients pin a platform API version
  (`X-Sovereign-API-Version`); deprecated versions return RFC 8594
  `Deprecation` + `Sunset` headers (`apiversion.py`). A version is supported for
  at least **one minor release** after it is marked deprecated.
- **Data lifecycle:** persisted-record shape changes ship a migration
  (`migrations.py`); old snapshots restore into newer code.

## Security patch SLA

See `SECURITY.md` for the vulnerability-response SLA. Patch releases for
Critical/High issues are cut out-of-band; the release workflow and changelog
discipline apply to them as to any release.

## Escalation path

1. Operator hits an issue → service runbook (`docs/runbooks/`) +
   `/readyz` / metrics / traces (one trace per provision).
2. Unresolved → on-call (PagerDuty/Opsgenie via the Alertmanager routing in
   `docs/slo.md`).
3. Security-sensitive → the private channel in `SECURITY.md`, not the public
   tracker.

## Continuous assurance

Beyond reactive support, the platform ships proactive assurance the owning team
operates: the continuous monitor (`scripts/continuous_monitor.py`), SLO
burn-rate alerts (`deploy/k8s/prometheus-rules.yaml`), the SSP evidence
validator (`scripts/ssp_validate.py`), and the backup/restore drill
(`python -m sovereign.backup drill`).
