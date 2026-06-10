# NIST 800-53 → ISO/IEC 27001:2022 Crosswalk (WS4)

The platform's control evidence is authored against NIST SP 800-53 Rev 5. This
crosswalk maps the implemented controls to **ISO/IEC 27001:2022 Annex A**, so
the same evidence supports an ISO-aligned assessment and widens the addressable
use cases beyond a FedRAMP/NIST posture.

The machine-readable source of truth is
[`crosswalk.json`](./crosswalk.json); `scripts/crosswalk_validate.py` (and
`tests/test_crosswalk.py`) enforce that **every NIST control mapped is one the
SSP actually documents** and that **every Annex A id is well-formed**, so the
crosswalk can't drift from the control package.

Run it:

```bash
python scripts/crosswalk_validate.py
```

Coverage: 33 NIST controls across AC / AU / CM / CP / IA / IR / RA / SC / SI,
mapped to the corresponding ISO/IEC 27001:2022 Annex A organizational, people,
and technological controls. Extend `crosswalk.json` as more controls are
implemented; the validator keeps it honest.
