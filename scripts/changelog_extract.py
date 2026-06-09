"""Extract one release's notes from CHANGELOG.md (E7).

The release workflow calls this with the tag version to build the GitHub
release body. Also maps a PEP 440 version (0.5.0a0) to the Keep-a-Changelog
heading form (0.5.0-alpha), since pyproject uses PEP 440 but the changelog
uses semver-style pre-release labels.

CLI: `python scripts/changelog_extract.py 0.5.0a0`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PRERELEASE = re.compile(r"^(\d+\.\d+\.\d+)(?:a(\d+)|b(\d+)|rc(\d+))?$")


def changelog_heading_version(version: str) -> str:
    """PEP 440 -> changelog heading form. 0.5.0a0 -> 0.5.0-alpha,
    1.2.0b1 -> 1.2.0-beta, 1.2.0rc2 -> 1.2.0-rc, 1.2.0 -> 1.2.0."""
    m = _PRERELEASE.match(version)
    if not m:
        return version
    base, a, b, rc = m.group(1), m.group(2), m.group(3), m.group(4)
    if a is not None:
        return f"{base}-alpha"
    if b is not None:
        return f"{base}-beta"
    if rc is not None:
        return f"{base}-rc"
    return base


def extract(version: str, changelog: str) -> str:
    """Return the changelog body for `version` (without its heading), or ""
    if there is no matching section."""
    heading = changelog_heading_version(version)
    lines = changelog.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            capturing = f"[{heading}]" in line
            continue
        if capturing:
            out.append(line)
    return "\n".join(out).strip()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: changelog_extract.py <version>", file=sys.stderr)
        return 2
    body = extract(args[0], (ROOT / "CHANGELOG.md").read_text())
    if not body:
        print(f"no CHANGELOG section for {args[0]}", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
