"""Single source of truth for the platform version (E7).

Every service reports this from its FastAPI `version=`, and a test asserts it
matches the `[project].version` in pyproject.toml — so the package version and
the running services can never drift (they previously reported 0.1.0 / 0.2.0 /
0.4.0 while the package was 0.5.0a0).
"""

from __future__ import annotations

__version__ = "0.5.0a0"
