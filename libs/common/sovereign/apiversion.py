"""API version negotiation + deprecation lifecycle (WS5).

Tenants pin a platform API version via the `X-Sovereign-API-Version` request
header. The chassis advertises the resolved version on every response and,
for a version that is being phased out, emits the RFC 8594 `Deprecation` and
`Sunset` headers — so a tenant whose workload an upgrade could break is warned
in-band, with a date, long before the version is removed. An unsupported
version is rejected (not silently served as `current`), so a client never
gets surprised by a contract it didn't ask for.

This is the API-surface half of the upgrade story; the persisted-data half is
the schema-migration framework in `migrations.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

#: Request header a client uses to pin the platform API version, and the
#: response header echoing the resolved version.
API_VERSION_HEADER = "X-Sovereign-API-Version"


@dataclass(frozen=True)
class ApiVersion:
    name: str
    deprecated: bool = False
    sunset: str | None = None  # ISO-8601 date the version stops being served


#: The version a client gets when it pins nothing.
CURRENT_API_VERSION = "2026-06-01"

#: Every version the platform still answers for. Date-based (Stripe/AWS style)
#: so additive changes don't require a new version and removals are scheduled.
SUPPORTED_API_VERSIONS: dict[str, ApiVersion] = {
    "2026-06-01": ApiVersion("2026-06-01"),
    # The initial GA contract, deprecated with a removal date so pinned tenants
    # get a Sunset warning and a migration window.
    "2026-01-01": ApiVersion("2026-01-01", deprecated=True, sunset="2026-12-31"),
}


class UnsupportedApiVersionError(Exception):
    def __init__(self, requested: str) -> None:
        super().__init__(requested)
        self.requested = requested


def resolve_api_version(requested: str | None) -> ApiVersion:
    """Resolve the pinned version, defaulting to current when none is given.
    Raises UnsupportedApiVersionError for an unknown version (fail loud)."""
    if not requested:
        return SUPPORTED_API_VERSIONS[CURRENT_API_VERSION]
    version = SUPPORTED_API_VERSIONS.get(requested.strip())
    if version is None:
        raise UnsupportedApiVersionError(requested.strip())
    return version


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """Negotiates the API version per request and annotates the response with
    the resolved version + deprecation/sunset headers."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            version = resolve_api_version(request.headers.get(API_VERSION_HEADER))
        except UnsupportedApiVersionError as exc:
            supported = ", ".join(sorted(SUPPORTED_API_VERSIONS))
            return Response(
                content=(
                    f'{{"title":"unsupported API version","status":400,'
                    f'"detail":"{exc.requested} is not supported; supported: {supported}"}}'
                ),
                status_code=400,
                media_type="application/problem+json",
            )
        response = await call_next(request)
        response.headers[API_VERSION_HEADER] = version.name
        if version.deprecated:
            # RFC 8594: signal deprecation and the removal date.
            response.headers["Deprecation"] = "true"
            if version.sunset:
                response.headers["Sunset"] = version.sunset
        return response


def install_api_versioning(app: FastAPI) -> None:
    app.add_middleware(ApiVersionMiddleware)
