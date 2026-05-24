#!/usr/bin/env python3
"""Sovereign Platform — continuous monitoring (Phase 5 task 5.2).

Runs a battery of compliance / drift checks against a live chassis
deployment. Each check returns a `CheckResult`; the runner prints a
table and exits non-zero on the first failure.

CI calls this on a cron (every hour) via the `continuous-monitor` job
in `.github/workflows/ci.yml`. The exit code drives pass/fail; failed
runs page on-call per `docs/incident-response.md` §2.

The checks are designed to be runnable against any deployment:

    OPA_URL=http://opa.gov.example:8181 \\
    AUDIT_SERVICE_URL=https://audit.gov.example \\
    SOVEREIGN_BEARER_TOKEN=... \\
    python3 scripts/continuous_monitor.py

Add `--once` to run a single pass and exit. Add `--check <name>` to
run a single named check (handy in incident response when you want
to verify just one thing).

NIST controls this check loop produces evidence for:
    CA-7, AU-2, AU-4, CM-7, CM-8, RA-5, SI-2, SI-4, IR-5.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import parse, request


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "PASS", "FAIL", "SKIP"
    detail: str
    nist_controls: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


# ── Helpers ──────────────────────────────────────────────────────────


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val if val else None


def _http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 10.0) -> tuple[int, bytes]:
    req = request.Request(url, method="GET", headers=headers or {})
    try:
        with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — explicit URL
            return resp.status, resp.read()
    except urlerror.HTTPError as exc:
        return exc.code, exc.read() if exc.fp else b""


# ── Checks ───────────────────────────────────────────────────────────


def check_opa_policy_tests() -> CheckResult:
    """OPA policy bundle still evaluates as documented + 100% coverage."""
    if shutil.which("opa") is None:
        return CheckResult(
            "opa_policy_tests", "SKIP", "opa binary not on PATH", ("CA-7", "CM-7")
        )
    proc = subprocess.run(
        ["opa", "test", str(ROOT / "policies"), "--coverage", "--format=json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return CheckResult(
            "opa_policy_tests",
            "FAIL",
            f"opa test exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}",
            ("CA-7", "CM-7"),
        )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return CheckResult(
            "opa_policy_tests",
            "FAIL",
            f"opa test produced malformed JSON: {exc}",
            ("CA-7",),
        )
    coverage = float(report.get("coverage", 0))
    if coverage < 100.0:
        return CheckResult(
            "opa_policy_tests",
            "FAIL",
            f"policy coverage {coverage:.1f}% < 100%",
            ("CA-7", "CM-7"),
        )
    return CheckResult(
        "opa_policy_tests",
        "PASS",
        f"opa test green at {coverage:.1f}% coverage",
        ("CA-7", "CM-7"),
    )


def check_audit_freshness(window_minutes: int = 60) -> CheckResult:
    """Audit events are landing inside the freshness window."""
    audit_url = _env("AUDIT_SERVICE_URL")
    token = _env("SOVEREIGN_BEARER_TOKEN") or _env("DEV_BEARER_TOKEN", "dev-token")
    if not audit_url:
        return CheckResult(
            "audit_freshness",
            "SKIP",
            "AUDIT_SERVICE_URL not configured",
            ("AU-2", "AU-4", "IR-5"),
        )
    since = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()
    qs = parse.urlencode({"since": since, "limit": 1})
    url = f"{audit_url.rstrip('/')}/events?{qs}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    code, body = _http_get(url, headers=headers, timeout=10)
    if code != 200:
        return CheckResult(
            "audit_freshness",
            "FAIL",
            f"audit GET /events returned {code}: {body.decode(errors='replace')[:200]}",
            ("AU-2", "AU-4", "IR-5"),
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return CheckResult(
            "audit_freshness",
            "FAIL",
            "audit GET /events returned non-JSON body",
            ("AU-2",),
        )
    count = int(payload.get("count", 0))
    if count == 0:
        return CheckResult(
            "audit_freshness",
            "FAIL",
            f"no audit events in the last {window_minutes} minutes — "
            "either the audit-service is degraded or the chassis has no traffic",
            ("AU-2", "AU-4", "IR-5"),
        )
    return CheckResult(
        "audit_freshness",
        "PASS",
        f"{count} event(s) inside last {window_minutes} min window",
        ("AU-2", "AU-4", "IR-5"),
    )


def check_state_drift() -> CheckResult:
    """Every DynamoDB ServiceInstance has a corresponding rendered S3 artefact."""
    # The chassis ships the reconciliation as a chassis library — call it
    # via a tiny subprocess so the monitor doesn't pull in boto3 + the
    # whole library surface unless it has to. Importing here would also
    # bind the monitor to the venv layout, which we want to avoid for
    # deployment in a sidecar-style cron pod.
    try:
        import boto3  # noqa: F401 — availability probe
    except ImportError:
        return CheckResult(
            "state_drift",
            "SKIP",
            "boto3 not installed; install with pip install boto3 to enable",
            ("CM-8", "CP-10"),
        )

    # Run the reconciliation in-process using the chassis Store + the same
    # S3 client the control plane uses.
    sys.path.insert(0, str(ROOT / "libs" / "common"))
    from sovereign.settings import get_settings
    from sovereign.store import Store

    s = get_settings()
    try:
        store = Store()
        instances = store.list_instances(limit=1000)
    except Exception as exc:  # noqa: BLE001
        # Missing credentials is a "no environment" situation (local
        # laptop without AWS configured). Treat as SKIP so the monitor
        # doesn't drown in noise; a production deployment always has
        # creds via IAM role or env vars and will see PASS / FAIL.
        msg = str(exc)
        if "Unable to locate credentials" in msg or "NoCredentialsError" in msg:
            return CheckResult(
                "state_drift",
                "SKIP",
                "no AWS credentials available — configure IAM role / env vars",
                ("CM-8", "CP-10"),
            )
        return CheckResult(
            "state_drift",
            "FAIL",
            f"DynamoDB read failed: {exc}",
            ("CM-8", "CP-10"),
        )

    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.aws_region,
    )

    missing: list[str] = []
    for inst in instances:
        key = f"instances/{inst.instance_id}/v{inst.version}/envoy.yaml"
        try:
            s3.head_object(Bucket=s.config_bucket, Key=key)
        except Exception:  # noqa: BLE001 — boto raises a family of errors here
            missing.append(f"{inst.instance_id}@v{inst.version}")

    if missing:
        return CheckResult(
            "state_drift",
            "FAIL",
            f"{len(missing)} instance(s) have no rendered S3 artefact: "
            f"{', '.join(missing[:5])}"
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""),
            ("CM-8", "CP-10"),
        )

    return CheckResult(
        "state_drift",
        "PASS",
        f"{len(instances)} instance(s) reconcile cleanly with S3",
        ("CM-8", "CP-10"),
    )


def check_image_scan_freshness(max_age_hours: int = 24) -> CheckResult:
    """A recent trivy scan report exists for each chassis image.

    The CI trivy job writes per-image SARIF artefacts; this check
    looks for the local report fingerprint emitted by the same CI job
    into ./.trivy-reports/<image>.timestamp. In a sidecar deployment
    the cron mounts the CI artefact volume; locally we skip if the
    directory is missing.
    """
    reports_dir = ROOT / ".trivy-reports"
    if not reports_dir.exists():
        return CheckResult(
            "image_scan_freshness",
            "SKIP",
            f"{reports_dir.relative_to(ROOT)} not present — wire the CI artefact mount",
            ("RA-5", "SI-2"),
        )
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    stale: list[str] = []
    seen = 0
    for ts_file in reports_dir.glob("*.timestamp"):
        seen += 1
        try:
            mtime = datetime.fromtimestamp(ts_file.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < cutoff:
            stale.append(f"{ts_file.stem} ({mtime.isoformat()})")
    if seen == 0:
        return CheckResult(
            "image_scan_freshness",
            "FAIL",
            f"no scan timestamps found in {reports_dir.relative_to(ROOT)}",
            ("RA-5", "SI-2"),
        )
    if stale:
        return CheckResult(
            "image_scan_freshness",
            "FAIL",
            f"{len(stale)} image(s) scanned > {max_age_hours}h ago: {', '.join(stale[:3])}",
            ("RA-5", "SI-2"),
        )
    return CheckResult(
        "image_scan_freshness",
        "PASS",
        f"all {seen} chassis image(s) scanned within {max_age_hours}h",
        ("RA-5", "SI-2"),
    )


def check_settings_sentinels() -> CheckResult:
    """When ENV=production, no dev sentinels remain active."""
    sys.path.insert(0, str(ROOT / "libs" / "common"))
    from sovereign.settings import _DEV_SENTINELS, get_settings

    s = get_settings()
    if s.env.lower() not in {"production", "prod"}:
        return CheckResult(
            "settings_sentinels",
            "SKIP",
            f"ENV={s.env}; sentinel gate is production-only",
            ("CM-6", "IA-5"),
        )
    active = [k for k, v in _DEV_SENTINELS.items() if getattr(s, k, None) == v]
    if active:
        return CheckResult(
            "settings_sentinels",
            "FAIL",
            f"dev sentinels still active in production: {', '.join(active)}",
            ("CM-6", "IA-5"),
        )
    return CheckResult(
        "settings_sentinels",
        "PASS",
        "no dev sentinels active",
        ("CM-6", "IA-5"),
    )


# ── Runner ───────────────────────────────────────────────────────────


CHECKS: dict[str, Callable[[], CheckResult]] = {
    "opa_policy_tests": check_opa_policy_tests,
    "audit_freshness": check_audit_freshness,
    "state_drift": check_state_drift,
    "image_scan_freshness": check_image_scan_freshness,
    "settings_sentinels": check_settings_sentinels,
}


def _print_table(results: list[CheckResult]) -> None:
    name_w = max(len(r.name) for r in results)
    status_w = 4
    print(f"{'name':<{name_w}}  {'res':<{status_w}}  {'controls':<20}  detail")
    print(f"{'-' * name_w}  {'-' * status_w}  {'-' * 20}  ------")
    for r in results:
        controls = ",".join(r.nist_controls) or "—"
        print(f"{r.name:<{name_w}}  {r.status:<{status_w}}  {controls:<20}  {r.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="append",
        choices=list(CHECKS),
        help="Run only the named check(s). Can be repeated.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single pass and exit (default behaviour; flag is kept for ergonomic parity with future loop mode).",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format.",
    )
    args = parser.parse_args(argv)

    selected = args.check or list(CHECKS)
    results: list[CheckResult] = []
    for name in selected:
        try:
            results.append(CHECKS[name]())
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(name, "FAIL", f"check raised: {exc}"))

    if args.format == "json":
        print(json.dumps(
            [
                {
                    "name": r.name,
                    "status": r.status,
                    "detail": r.detail,
                    "nist_controls": list(r.nist_controls),
                }
                for r in results
            ],
            indent=2,
        ))
    else:
        _print_table(results)

    # Exit non-zero on any FAIL; SKIPs do not fail the run.
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
