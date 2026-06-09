"""Validate the SSP control package against the codebase (E6).

The System Security Plan documents each NIST 800-53 control as a table row:
`| Control | Status | Implementation | Evidence |`, where Evidence cites the
files that implement/test the control (backtick-quoted, optionally with a
`::symbol` suffix). An authorization package is only credible if that evidence
actually exists, so this parses every control table and checks that each cited
path resolves in the repo. It also summarises coverage by status.

CLI: `python scripts/ssp_validate.py` — exits non-zero if any evidence path is
missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTROLS_DIR = ROOT / "docs" / "ssp" / "controls"

_CONTROL_ID_RE = re.compile(r"\b([A-Z]{2}-\d+(?:\(\d+\))?)\b")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# A cited token looks like a repo path: has a slash and a file-ish extension.
_PATH_RE = re.compile(r"^[\w./-]+\.\w+$")


@dataclass
class ControlRow:
    control: str
    status: str
    evidence_paths: list[str]
    source: str


@dataclass
class Report:
    rows: list[ControlRow] = field(default_factory=list)
    missing: list[tuple[str, str, str]] = field(default_factory=list)  # (control, path, source)

    @property
    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            key = _status_bucket(row.status)
            counts[key] = counts.get(key, 0) + 1
        return counts


def _status_bucket(status: str) -> str:
    s = status.lower()
    if "implement" in s:
        return "implemented"
    if "inherit" in s:
        return "inherited"
    if "planned" in s or "partial" in s or "todo" in s:
        return "planned"
    return "other"


def _evidence_paths(cell: str) -> list[str]:
    paths: list[str] = []
    for span in _BACKTICK_RE.findall(cell):
        token = span.split("::", 1)[0].strip()
        if _PATH_RE.match(token) and "/" in token:
            paths.append(token)
    return paths


def _parse_file(path: Path) -> list[ControlRow]:
    rows: list[ControlRow] = []
    for line in path.read_text().splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        control_match = _CONTROL_ID_RE.search(cells[0])
        if not control_match or cells[1].lower() in {"status", "---", ":---"}:
            continue
        rows.append(
            ControlRow(
                control=control_match.group(1),
                status=cells[1],
                evidence_paths=_evidence_paths(cells[3]),
                source=path.name,
            )
        )
    return rows


def validate() -> Report:
    report = Report()
    for md in sorted(CONTROLS_DIR.glob("*.md")):
        if md.name == "README.md":
            continue
        for row in _parse_file(md):
            report.rows.append(row)
            for rel in row.evidence_paths:
                if not (ROOT / rel).exists():
                    report.missing.append((row.control, rel, row.source))
    return report


def main() -> int:
    report = validate()
    cited = sum(len(r.evidence_paths) for r in report.rows)
    print(f"SSP controls parsed: {len(report.rows)} (evidence paths cited: {cited})")
    print("coverage by status:")
    for status, count in sorted(report.by_status.items()):
        print(f"  {status:>12}: {count}")
    if report.missing:
        print(f"\nMISSING evidence ({len(report.missing)}):")
        for control, rel, source in report.missing:
            print(f"  [{source}] {control}: {rel}")
        return 1
    print("\nall cited evidence resolves ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
