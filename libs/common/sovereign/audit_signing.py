"""Audit event signing helpers.

Hash chaining shows whether the event sequence was altered. A detached
service signature additionally proves which audit-service key accepted
the row.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives.serialization import load_pem_private_key

from .models import AuditEvent
from .settings import get_settings


def canonical_signing_payload(event: AuditEvent) -> bytes:
    return json.dumps(
        event.model_dump(mode="json", exclude={"signature", "signature_key_id"}),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@lru_cache
def _private_key() -> Any | None:
    s = get_settings()
    pem = s.audit_signing_private_key_pem.strip()
    if not pem:
        return None
    pem = pem.replace("\\n", "\n")
    return load_pem_private_key(pem.encode("utf-8"), password=None)


def sign_audit_event(event: AuditEvent) -> AuditEvent:
    if event.signature:
        return event
    s = get_settings()
    key = _private_key()
    if key is None:
        if s.require_audit_signing:
            raise RuntimeError("audit signing is required but no private key is configured")
        return event
    signature = key.sign(canonical_signing_payload(event))
    return event.model_copy(
        update={
            "signature_key_id": s.audit_signature_key_id,
            "signature": base64.b64encode(signature).decode("ascii"),
        }
    )


def reset_audit_signing_cache() -> None:
    _private_key.cache_clear()
