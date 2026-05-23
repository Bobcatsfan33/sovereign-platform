"""GitHub connector — list repos and ingest files.

Supports both github.com and GitHub Enterprise (set host in credentials).
Auth: personal access token (PAT) for now; GitHub App auth is on the
backlog. Uses httpx directly rather than pulling in PyGithub — keeps the
dependency surface small and the connector test-friendly via
`httpx.MockTransport`.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, ClassVar

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

from ..catalog import ConnectorCatalogEntry, ParameterSchema
from .base import BaseConnector
from .types import (
    ConnectionResult,
    ConnectorCredentials,
    HealthStatus,
    IngestOptions,
    IngestResult,
    ResourceDescriptor,
)

logger = logging.getLogger("sovereign.connectors.github")


class GitHubConnector(BaseConnector):
    connector_type: ClassVar[str] = "github"

    @classmethod
    def catalog_entry(cls) -> ConnectorCatalogEntry:
        return ConnectorCatalogEntry(
            connector_type=cls.connector_type,
            name="github",
            description="GitHub.com and GitHub Enterprise — list repos, ingest files.",
            pack="chassis",
            capabilities=["list", "ingest", "github-enterprise"],
            config_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "required": ["kind", "data"],
                    "properties": {
                        "kind": {"const": "github_pat"},
                        "data": {
                            "type": "object",
                            "required": ["token"],
                            "properties": {
                                "token": {
                                    "type": "string",
                                    "description": "Personal access token; classic or fine-grained.",
                                },
                                "host": {
                                    "type": "string",
                                    "description": "API host. github.com -> 'api.github.com'; "
                                    "GHE -> 'github.example.gov/api/v3'.",
                                    "default": "api.github.com",
                                },
                            },
                        },
                    },
                }
            ),
        )

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        # Tests inject `transport` (httpx.MockTransport) without touching
        # the network; production leaves it None and httpx uses the real
        # transport. The client itself is built in connect().
        self._inject_transport = transport
        self._client: httpx.AsyncClient | None = None
        self._principal: str = ""
        self._host: str = "api.github.com"

    async def connect(self, credentials: ConnectorCredentials) -> ConnectionResult:
        """Accepts:
            kind='github_pat' data={'token', 'host'?}
                host defaults to 'api.github.com'; GHE is e.g.
                'github.example.gov/api/v3'.
        """
        if credentials.kind != "github_pat":
            return ConnectionResult(
                ok=False,
                detail=f"unsupported credential kind for GitHub: {credentials.kind!r}",
            )
        token = credentials.data.get("token")
        if not token:
            return ConnectionResult(ok=False, detail="missing token in credentials")
        self._host = credentials.data.get("host", "api.github.com")

        client_kwargs: dict[str, Any] = {
            "base_url": f"https://{self._host}",
            "headers": {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            "timeout": 10.0,
        }
        if self._inject_transport is not None:
            client_kwargs["transport"] = self._inject_transport

        self._client = httpx.AsyncClient(**client_kwargs)
        try:
            r = await self._client.get("/user")
        except httpx.HTTPError as exc:
            return ConnectionResult(ok=False, detail=str(exc))
        if r.status_code != 200:
            return ConnectionResult(
                ok=False, detail=f"/user returned {r.status_code}: {r.text[:200]}"
            )
        payload = r.json()
        self._principal = payload.get("login", "github-user")
        return ConnectionResult(ok=True, principal=self._principal)

    async def list_resources(
        self, filters: dict | None = None
    ) -> list[ResourceDescriptor]:
        """Filters:
            {} or None                 -> list repos visible to the user.
            {'org': X}                 -> list repos under org X.
            {'repo': 'owner/name', 'path': P} -> list contents of path in repo.
            {'per_page': N}            -> page size (default 30, max 100).
        """
        if self._client is None:
            raise RuntimeError("GitHubConnector.connect() must run before list_resources")
        filters = filters or {}
        per_page = min(int(filters.get("per_page", 30)), 100)

        # Listing inside a repo (browse a directory).
        if "repo" in filters:
            path = filters.get("path", "").lstrip("/")
            url = f"/repos/{filters['repo']}/contents/{path}"
            r = await self._client.get(url)
            if r.status_code != 200:
                logger.warning("GitHub list contents failed: %s %s", r.status_code, r.text[:200])
                return []
            items = r.json() if isinstance(r.json(), list) else [r.json()]
            return [
                ResourceDescriptor(
                    connector_type=self.connector_type,
                    resource_id=f"{filters['repo']}@{item['sha']}:{item['path']}",
                    name=item["name"],
                    kind=item.get("type", "file"),
                    size_bytes=item.get("size"),
                    metadata={
                        "repo": filters["repo"],
                        "path": item["path"],
                        "sha": item["sha"],
                        "download_url": item.get("download_url"),
                    },
                )
                for item in items
            ]

        # Listing repos.
        url = f"/orgs/{filters['org']}/repos" if "org" in filters else "/user/repos"
        r = await self._client.get(url, params={"per_page": per_page})
        if r.status_code != 200:
            logger.warning("GitHub list repos failed: %s %s", r.status_code, r.text[:200])
            return []
        return [
            ResourceDescriptor(
                connector_type=self.connector_type,
                resource_id=repo["full_name"],
                name=repo["full_name"],
                kind="repository",
                metadata={
                    "default_branch": repo.get("default_branch"),
                    "visibility": repo.get("visibility"),
                    "private": repo.get("private"),
                },
            )
            for repo in r.json()
        ]

    async def ingest(
        self, resource: ResourceDescriptor, options: IngestOptions
    ) -> IngestResult:
        """Pull a single file from GitHub and stage it in S3.

        Resource shape: kind='file', metadata contains 'repo' and 'path'.
        We fetch via `/repos/{repo}/contents/{path}` which returns base64-
        encoded content for files <1MB. Larger files use the blob API
        (Phase 1 keeps to the simple path; large-blob support is on the
        backlog)."""
        if self._client is None:
            raise RuntimeError("GitHubConnector.connect() must run before ingest")
        if resource.kind not in {"file"}:
            return IngestResult(
                ok=False,
                detail=f"GitHub ingest expects kind='file', got {resource.kind!r}",
            )
        repo = resource.metadata.get("repo")
        path = resource.metadata.get("path")
        if not repo or not path:
            return IngestResult(ok=False, detail="missing repo/path in resource metadata")

        r = await self._client.get(f"/repos/{repo}/contents/{path}")
        if r.status_code != 200:
            return IngestResult(
                ok=False, detail=f"source fetch returned {r.status_code}"
            )
        payload = r.json()
        if payload.get("encoding") != "base64" or "content" not in payload:
            return IngestResult(
                ok=False, detail="unsupported content encoding (large blob path NYI)"
            )
        body = base64.b64decode(payload["content"])

        if options.max_size_bytes is not None and len(body) > options.max_size_bytes:
            return IngestResult(
                ok=False,
                detail=f"file {len(body)} bytes exceeds max_size_bytes={options.max_size_bytes}",
            )

        # Stage to platform S3. The connector reuses the platform's S3
        # settings (no separate per-connector destination credentials yet —
        # comes with the Vault integration in Phase 3).
        from ..settings import get_settings

        s = get_settings()
        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=s.s3_endpoint,
                aws_access_key_id=s.s3_access_key,
                aws_secret_access_key=s.s3_secret_key,
                region_name=s.aws_region,
            )
            staged_key = f"{options.destination_prefix.rstrip('/')}/{repo}/{path}".lstrip("/")
            s3.put_object(
                Bucket=options.destination_bucket,
                Key=staged_key,
                Body=body,
                ContentType="application/octet-stream",
            )
        except (ClientError, BotoCoreError) as exc:
            return IngestResult(ok=False, detail=f"staging write failed: {exc}")

        return IngestResult(
            ok=True,
            items_count=1,
            bytes_transferred=len(body),
            staged_paths=[f"{options.destination_bucket}/{staged_key}"],
        )

    async def health_check(self) -> HealthStatus:
        if self._client is None:
            return HealthStatus(ok=False, message="not connected")
        try:
            r = await self._client.get("/rate_limit")
        except httpx.HTTPError as exc:
            return HealthStatus(ok=False, message=str(exc))
        if r.status_code != 200:
            return HealthStatus(ok=False, message=f"/rate_limit returned {r.status_code}")
        return HealthStatus(ok=True, message=f"principal={self._principal}")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
