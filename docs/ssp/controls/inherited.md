# Fully Inherited and Organizational Controls

This file lists Moderate-baseline NIST 800-53 controls that the chassis
**does not implement directly** because they map fully to either:

- the hosting environment (AWS GovCloud / Azure Gov FedRAMP-authorised
  services), or
- the operating agency's organizational programme (HR, training,
  facility security, etc.).

| Family | Controls | Source |
| --- | --- | --- |
| AT | AT-1, AT-2, AT-3, AT-4 | Agency awareness and training programme. |
| MA | MA-1, MA-2, MA-3, MA-4, MA-5, MA-6 | Hosting cloud (rack maintenance, firmware updates) + agency change-management. |
| MP | MP-1, MP-2, MP-3, MP-4, MP-5, MP-6, MP-7 | Hosting cloud (media storage / handling / disposal) + agency for any physical media in scope. |
| PE | PE-1 .. PE-23 | Hosting cloud — see [`pe.md`](./pe.md). |
| PS | PS-1, PS-2, PS-3, PS-4, PS-5, PS-6, PS-7, PS-8 | Agency HR / personnel security. |
| PT | PT-1, PT-2, PT-3, PT-4, PT-5, PT-6, PT-7, PT-8 | Agency privacy programme. |
| PM | All | Agency security programme management. |
| CA-2, CA-5, CA-6, CA-8, CA-9 | | Agency assessment and authorisation programme. CA-7 (continuous monitoring) IS chassis-implemented — see [`../README.md`](../README.md). |
| CP-1 through CP-8 | | Agency contingency plan. CP-9 / CP-10 IS chassis-implemented — see [`cp.md`](./cp.md). |
| AC-1, AU-1, CM-1, IA-1, IR-1, RA-1, SA-1, SC-1, SI-1 | The "-1" policy-and-procedures controls. | Agency security policy. The chassis-specific implementation references live in each family chapter. |

## Hosting-environment evidence

For controls inherited from AWS GovCloud or Azure Gov, the agency
includes the relevant CSP FedRAMP authorisation package as an
appendix to its own SSP. The chassis SSP scaffold here does NOT
duplicate that material; it references it.

## Organizational programme references

| Document | Owns |
| --- | --- |
| Agency Information Security Programme Plan | AT, PM, PS family |
| Agency Privacy Plan | PT family |
| Agency Contingency Plan | CP family (less CP-9/10) |
| Agency Configuration Management Plan | CM-1 |
| Agency Risk Management Plan | RA-1, RA-3 |
| Agency Incident Response Plan | IR-1, IR-2, IR-3, IR-7 |
