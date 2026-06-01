"""Durable disk spool for audit events (S5 hardening).

The audit service degrades gracefully when ClickHouse is unreachable by
holding events in a bounded in-memory ring buffer. The failure mode of
that buffer is *silent data loss* once the cap is hit — unacceptable for
a system whose value proposition is AU-2/AU-4 audit completeness.

This module adds an append-only JSONL spool on local disk. When the
in-memory buffer overflows (or on graceful shutdown) events are written
here instead of dropped; on the next successful ClickHouse insert the
spool is drained back through the normal persistence path. The spool is
line-oriented and fsync-on-write so a crash loses at most the event
currently being written, satisfying the durability the ring buffer alone
could not.

The spool is intentionally simple (no rotation/compaction beyond a size
cap) — for the audit volumes the chassis targets this is sufficient, and
the interface is small enough to swap for a managed queue (SQS/Kafka)
without touching call sites.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path

from .models import AuditEvent


class AuditSpool:
    """Append-only, fsync'd JSONL spool of AuditEvents on local disk."""

    def __init__(self, path: str | os.PathLike[str], *, max_bytes: int = 50_000_000) -> None:
        self._path = Path(path)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: AuditEvent) -> bool:
        """Durably append one event. Returns False if the spool is at its
        size cap (caller then knows the event was NOT spooled and can log
        a hard error rather than assume durability)."""
        line = json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
        with self._lock:
            try:
                if self._path.exists() and self._path.stat().st_size >= self._max_bytes:
                    return False
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError:
                return False
        return True

    def drain(self) -> list[AuditEvent]:
        """Atomically take every spooled event and clear the spool.

        The caller is responsible for re-persisting the returned events;
        if persistence fails it should `append` them back. Returns an
        empty list when the spool is absent or empty."""
        with self._lock:
            if not self._path.exists():
                return []
            try:
                raw = self._path.read_text(encoding="utf-8")
            except OSError:
                return []
            # Truncate first so a concurrent appender after drain doesn't
            # lose its event; we re-read nothing here.
            with contextlib.suppress(OSError):
                self._path.unlink()
        events: list[AuditEvent] = []
        for ln in raw.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                events.append(AuditEvent.model_validate_json(ln))
            except ValueError:
                # A torn final line (crash mid-write) is skipped rather
                # than aborting the whole drain.
                continue
        return events

    def count(self) -> int:
        """Best-effort count of spooled events (number of lines)."""
        with self._lock:
            if not self._path.exists():
                return 0
            try:
                with open(self._path, encoding="utf-8") as fh:
                    return sum(1 for ln in fh if ln.strip())
            except OSError:
                return 0
