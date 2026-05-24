# NIST 800-53 Rev 5 Control Family Index

Coverage matrix for the Sovereign Platform base chassis. The Moderate
baseline contains controls from 18 families. The chassis implements
~30 controls directly and inherits the rest from the hosting
environment (AWS GovCloud / Azure Gov) or the operating agency.

| Family | Name | Chapter | Chassis-implemented controls |
| --- | --- | --- | --- |
| AC | Access Control | [ac.md](./ac.md) | AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-12 |
| AT | Awareness and Training | (organizational) | — |
| AU | Audit and Accountability | [au.md](./au.md) | AU-2, AU-3, AU-4, AU-6, AU-7, AU-8, AU-9, AU-11, AU-12 |
| CA | Assessment, Authorization, and Monitoring | (organizational + 5.2) | CA-7 (continuous monitoring) |
| CM | Configuration Management | [cm.md](./cm.md) | CM-2, CM-3, CM-6, CM-7, CM-8, CM-9 |
| CP | Contingency Planning | [cp.md](./cp.md) | CP-9 (chassis state backup), CP-10 |
| IA | Identification and Authentication | [ia.md](./ia.md) | IA-2, IA-5, IA-8 |
| IR | Incident Response | [ir.md](./ir.md) | IR-4, IR-5, IR-6 |
| MA | Maintenance | (organizational + inherited) | — |
| MP | Media Protection | (inherited) | — |
| PE | Physical and Environmental Protection | (inherited) | — |
| PL | Planning | [→ ../system-description.md] | PL-2, PL-8 |
| PM | Program Management | (organizational) | — |
| PS | Personnel Security | (organizational) | — |
| PT | Personally Identifiable Information Processing and Transparency | (organizational) | — |
| RA | Risk Assessment | [ra.md](./ra.md) | RA-5 (vulnerability scanning) |
| SA | System and Services Acquisition | [sa.md](./sa.md) | SA-11 (developer testing) |
| SC | System and Communications Protection | [sc.md](./sc.md) | SC-4, SC-7, SC-8, SC-12, SC-13, SC-23, SC-28 |
| SI | System and Information Integrity | [si.md](./si.md) | SI-2 (flaw remediation via trivy), SI-4 (audit/monitoring), SI-10 (input validation), SI-11 (error handling) |

See [`inherited.md`](./inherited.md) for controls that map fully to the
hosting environment and require no chassis implementation.
