"""Mesh mTLS peer-identity extraction (E2).

In the hardened posture the platform terminates mTLS at a trusted service
mesh / front door (Envoy). After verifying the client certificate, Envoy
forwards the validated peer identity in the ``X-Forwarded-Client-Cert``
(XFCC) header and — crucially — sanitises any client-supplied copy, so a
caller on a direct path cannot forge it. This module turns that header into
the peer's SPIFFE URI SAN.

Why this exists: ``require_bearer`` previously trusted a plain
``X-Sovereign-Workload-Identity`` / ``X-SPIFFE-ID`` header from *any* caller.
That is safe only if the service is unreachable except through the mesh.
XFCC moves the trust to something the mesh proves cryptographically, so the
identity is non-spoofable even if the port is reachable directly.

XFCC grammar (Envoy): a comma-separated list of elements, one per cert, the
downstream peer first. Each element is a semicolon-separated list of
``Key=Value`` pairs (``By``, ``Hash``, ``Cert``, ``Chain``, ``Subject``,
``URI``, ``DNS``). Values that contain separators are double-quoted with
backslash escaping. The SPIFFE id is the ``URI`` SAN of the leaf element.
"""

from __future__ import annotations

#: Header Envoy uses to forward the verified client certificate after it
#: terminates mTLS at the mesh / front door.
XFCC_HEADER = "X-Forwarded-Client-Cert"


def _split_unquoted(value: str, sep: str) -> list[str]:
    """Split ``value`` on ``sep``, ignoring separators inside double quotes.

    A backslash escapes the next character (Envoy escapes embedded quotes as
    ``\\"``), so an escaped quote does not open/close a quoted span."""
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    escaped = False
    for ch in value:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\":
            current.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
            continue
        if ch == sep and not in_quotes:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _unquote(value: str) -> str:
    """Strip surrounding double quotes and unescape ``\\"`` / ``\\\\``."""
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        out: list[str] = []
        escaped = False
        for ch in inner:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                escaped = True
            else:
                out.append(ch)
        return "".join(out)
    return value


def parse_xfcc_identity(raw: str | None) -> str | None:
    """Return the leaf peer's ``URI`` SAN (SPIFFE id) from an XFCC header,
    or ``None`` if the header is absent/blank or carries no ``URI`` field.

    Only the first element (the immediate downstream peer presented by the
    mesh) is consulted; intermediate/CA certs in later elements are ignored.
    Key matching is case-insensitive; the first ``URI`` wins."""
    if not raw or not raw.strip():
        return None
    leaf = _split_unquoted(raw, ",")[0]
    for pair in _split_unquoted(leaf, ";"):
        key, sep, val = pair.partition("=")
        if not sep:
            continue
        if key.strip().upper() == "URI":
            identity = _unquote(val)
            return identity or None
    return None
