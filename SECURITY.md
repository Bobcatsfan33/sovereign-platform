# Security Policy

## Supported Versions

The platform is pre-1.0; security fixes land on the latest minor release.
Operators should track the most recent tagged release.

| Version | Supported |
| --- | --- |
| 0.5.x | ✅ |
| < 0.5 | ❌ |

## Reporting a Vulnerability

**Do not open a public issue for security reports.** Report privately via:

- **GitHub Security Advisories** — "Report a vulnerability" on the repository's
  Security tab (preferred; gives a private coordination space), or
- **Email** — security@sovereign-platform.example (replace with the owning
  team's real address before GA).

Please include a description, affected version/commit, reproduction steps, and
impact. A CVSS estimate helps triage but is not required.

## Response SLA

| Stage | Target |
| --- | --- |
| Acknowledge receipt | 3 business days |
| Initial triage + severity | 10 business days |
| Fix for Critical/High | 30 days (or a documented mitigation) |
| Fix for Medium/Low | next scheduled release |

## Coordinated Disclosure

We follow coordinated disclosure: we ask reporters to give us up to **90 days**
to ship a fix before public disclosure, and we will credit reporters who wish
to be named. A security advisory and a patched release are published together.

## Scope

In scope: the chassis services (broker, control-plane, audit-service,
metering-service), the shared libraries, the policy bundles, and the deployment
manifests in this repository. Out of scope: third-party dependencies (report to
their maintainers) and an operator's own deployment misconfiguration.

The secure-by-default posture (managed secrets + fail-closed gates, mesh mTLS,
hash-chained audit, fail-closed policy obligations) is intended to be verified
by an independent penetration test before GA — see `docs/release.md` GA gates.
