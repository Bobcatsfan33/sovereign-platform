# Release Process (E7)

The chassis follows [Semantic Versioning](https://semver.org/). Pre-1.0 alpha
releases may make breaking changes between minor versions. The package version
in `pyproject.toml`, the runtime constant `sovereign.version.__version__`, and
every service's `FastAPI(version=…)` are a single source — a test
(`tests/test_version.py`) fails if they drift.

## Cutting a release

1. **Bump the version** in `libs/common/sovereign/version.py` and
   `pyproject.toml` (keep them identical — the test enforces it).
2. **Update `CHANGELOG.md`**: add a `## [<version>] — <date>` section
   (Keep a Changelog format). The release notes come verbatim from this
   section (`scripts/changelog_extract.py`).
3. **Open a PR**, land it green (the full CI gate must pass).
4. **Tag and push**: `git tag v<version> && git push origin v<version>`.
   - The `release` workflow refuses to publish if the tag doesn't match the
     `pyproject` version, then creates the GitHub release from the changelog
     section (marked pre-release for `aN`/`bN`/`rcN` versions).

Version forms: `pyproject` uses PEP 440 (`0.5.0a0`); the changelog heading uses
the semver pre-release form (`0.5.0-alpha`). `changelog_extract.py` maps
between them.

## GA gates (1.0)

Beyond green CI, a GA (`1.0.0`) release additionally requires:

- **Independent penetration test** of the deployed boundary, with findings
  triaged into the POA&M (`docs/ssp/poam.md`) and criticals remediated.
- **A pilot tenant** run end-to-end (provision → use → deprovision) in a
  representative environment, with the mesh in strict mode and SLOs observed
  green over the pilot window.
- **SSP evidence validated** (`python scripts/ssp_validate.py`) and the
  authorization package current.
- **Operator + tenant docs** complete.

These gates are process, not CI; track them on the release checklist for the
GA milestone.
