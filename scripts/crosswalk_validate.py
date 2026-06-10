"""Validate the NIST -> ISO/IEC 27001 control crosswalk (WS4).

A second framework materially widens the addressable use cases, but only if
the crosswalk is real: every NIST control it maps must be a control the SSP
actually documents (no phantom source), and every target id must be a
well-formed ISO/IEC 27001:2022 Annex A control. This checks both and reports
coverage.

CLI: `python scripts/crosswalk_validate.py` — exits non-zero on any problem.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CROSSWALK = ROOT / "docs" / "ssp" / "crosswalk.json"

# ISO/IEC 27001:2022 Annex A: themes 5 (Organizational), 6 (People),
# 7 (Physical), 8 (Technological), e.g. A.5.15, A.8.24.
_ISO_RE = re.compile(r"^A\.[5678]\.\d{1,2}$")


def _ssp_control_ids() -> set[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ssp_validate

    return {row.control for row in ssp_validate.validate().rows}


def validate() -> list[str]:
    """Return a list of problem strings (empty when the crosswalk is valid)."""
    problems: list[str] = []
    data = json.loads(CROSSWALK.read_text())
    mappings: dict[str, list[str]] = data.get("mappings", {})
    ssp_ids = _ssp_control_ids()

    for nist, iso_ids in mappings.items():
        if nist not in ssp_ids:
            problems.append(f"{nist}: not a documented SSP control")
        if not iso_ids:
            problems.append(f"{nist}: no target controls")
        for iso in iso_ids:
            if not _ISO_RE.match(iso):
                problems.append(f"{nist}: malformed Annex A id {iso!r}")
    return problems


def main() -> int:
    data = json.loads(CROSSWALK.read_text())
    mappings = data.get("mappings", {})
    problems = validate()
    print(
        f"crosswalk {data.get('source_framework')} -> {data.get('target_framework')}: "
        f"{len(mappings)} controls mapped"
    )
    if problems:
        print(f"\nPROBLEMS ({len(problems)}):")
        for p in problems:
            print(f"  {p}")
        return 1
    print("crosswalk valid ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
