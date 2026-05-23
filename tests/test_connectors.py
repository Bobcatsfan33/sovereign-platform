"""Tests for the pluggable connector subsystem (Phase 1 tasks 1.4, 1.5, 1.6)."""

from __future__ import annotations

import base64
import json
import logging
from typing import ClassVar

import boto3
import httpx
import pytest
from moto import mock_aws
from sovereign.connectors import (
    BaseConnector,
    ConnectorCredentials,
    GitHubConnector,
    HealthStatus,
    IngestOptions,
    IngestResult,
    ResourceDescriptor,
    S3Connector,
    get_connector,
    register_connector,
    registry,
)
from sovereign.connectors.types import ConnectionResult

# ── BaseConnector + registry contract ─────────────────────────────────


class _Dummy(BaseConnector):
    connector_type: ClassVar[str] = "test-dummy-conn"

    async def connect(self, credentials):  # type: ignore[no-untyped-def]
        return ConnectionResult(ok=True, principal="dummy")

    async def list_resources(self, filters=None):  # type: ignore[no-untyped-def]
        return []

    async def ingest(self, resource, options):  # type: ignore[no-untyped-def]
        return IngestResult(ok=True)

    async def health_check(self):  # type: ignore[no-untyped-def]
        return HealthStatus(ok=True)


def test_subclass_requires_connector_type() -> None:
    with pytest.raises(TypeError, match="connector_type"):

        class _Bad(BaseConnector):
            async def connect(self, credentials):  # type: ignore[no-untyped-def]
                ...

            async def list_resources(self, filters=None):  # type: ignore[no-untyped-def]
                ...

            async def ingest(self, resource, options):  # type: ignore[no-untyped-def]
                ...

            async def health_check(self):  # type: ignore[no-untyped-def]
                ...


def test_register_and_get() -> None:
    register_connector(_Dummy)
    assert "test-dummy-conn" in registry.connector_types()
    assert get_connector("test-dummy-conn") is _Dummy


def test_require_unknown_raises() -> None:
    with pytest.raises(KeyError):
        registry.require("nope")


def test_chassis_connectors_pre_registered() -> None:
    assert registry.get("s3") is S3Connector
    assert registry.get("github") is GitHubConnector


def test_override_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    register_connector(_Dummy)

    class _Other(BaseConnector):
        connector_type: ClassVar[str] = "test-dummy-conn"

        async def connect(self, credentials):  # type: ignore[no-untyped-def]
            ...

        async def list_resources(self, filters=None):  # type: ignore[no-untyped-def]
            ...

        async def ingest(self, resource, options):  # type: ignore[no-untyped-def]
            ...

        async def health_check(self):  # type: ignore[no-untyped-def]
            ...

    caplog.set_level(logging.WARNING, logger="sovereign.connectors")
    register_connector(_Other)
    assert any("replaced" in r.message for r in caplog.records)


# ── S3Connector ───────────────────────────────────────────────────────


async def test_s3_connect_rejects_unknown_kind() -> None:
    c = S3Connector()
    r = await c.connect(ConnectorCredentials(kind="weird-thing"))
    assert not r.ok
    assert "unsupported credential kind" in r.detail


async def test_s3_connect_list_ingest_round_trip() -> None:
    with mock_aws():
        # Source data
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="source-bucket")
        s3.put_object(Bucket="source-bucket", Key="docs/readme.md", Body=b"hello world")
        s3.put_object(Bucket="source-bucket", Key="docs/notes.txt", Body=b"more bytes")
        # Staging dest
        s3.create_bucket(Bucket="staging-bucket")

        conn = S3Connector()
        result = await conn.connect(
            ConnectorCredentials(
                kind="aws_access_key",
                data={
                    "access_key_id": "testing",
                    "secret_access_key": "testing",
                    "region": "us-east-1",
                },
            )
        )
        assert result.ok, result.detail

        # list buckets
        buckets = await conn.list_resources()
        names = {b.name for b in buckets}
        assert {"source-bucket", "staging-bucket"} <= names
        assert all(b.kind == "bucket" for b in buckets)

        # list objects in source-bucket with prefix
        objs = await conn.list_resources({"bucket": "source-bucket", "prefix": "docs/"})
        assert {o.name for o in objs} == {"docs/readme.md", "docs/notes.txt"}
        assert all(o.kind == "object" for o in objs)
        assert all(o.connector_type == "s3" for o in objs)

        # ingest one object
        target = next(o for o in objs if o.name == "docs/readme.md")
        ir = await conn.ingest(
            target,
            IngestOptions(destination_bucket="staging-bucket", destination_prefix="ingest/"),
        )
        assert ir.ok, ir.detail
        assert ir.bytes_transferred == len(b"hello world")
        # Verify it landed in staging
        staged = s3.get_object(Bucket="staging-bucket", Key="ingest/docs/readme.md")
        assert staged["Body"].read() == b"hello world"

        # health_check
        hs = await conn.health_check()
        assert hs.ok


async def test_s3_ingest_max_size_rejects_oversize() -> None:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="src")
        s3.create_bucket(Bucket="dst")
        s3.put_object(Bucket="src", Key="big", Body=b"x" * 100)

        conn = S3Connector()
        await conn.connect(
            ConnectorCredentials(
                kind="aws_access_key",
                data={"access_key_id": "k", "secret_access_key": "s"},
            )
        )
        obj = (await conn.list_resources({"bucket": "src"}))[0]
        ir = await conn.ingest(
            obj,
            IngestOptions(destination_bucket="dst", max_size_bytes=10),
        )
        assert not ir.ok
        assert "exceeds max_size_bytes" in ir.detail


async def test_s3_ingest_rejects_non_object_resource() -> None:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="src")
        conn = S3Connector()
        await conn.connect(
            ConnectorCredentials(
                kind="aws_access_key",
                data={"access_key_id": "k", "secret_access_key": "s"},
            )
        )
        bucket_resource = ResourceDescriptor(
            connector_type="s3", resource_id="src", name="src", kind="bucket"
        )
        ir = await conn.ingest(
            bucket_resource,
            IngestOptions(destination_bucket="src"),
        )
        assert not ir.ok
        assert "kind='object'" in ir.detail


async def test_s3_health_check_when_not_connected() -> None:
    conn = S3Connector()
    hs = await conn.health_check()
    assert not hs.ok
    assert "not connected" in hs.message


async def test_s3_list_resources_requires_connect() -> None:
    conn = S3Connector()
    with pytest.raises(RuntimeError, match="connect"):
        await conn.list_resources()


# ── GitHubConnector ───────────────────────────────────────────────────


def _gh_handler(responses: dict[str, dict]) -> object:
    """Build an httpx MockTransport handler that returns canned responses
    keyed by URL path."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        # Trim query string for matching simplicity.
        spec = responses.get(path)
        if spec is None:
            return httpx.Response(404, json={"message": f"no fixture for {path}"})
        return httpx.Response(spec.get("status", 200), json=spec["body"])

    return httpx.MockTransport(handler)


async def test_github_connect_rejects_unknown_kind() -> None:
    c = GitHubConnector()
    r = await c.connect(ConnectorCredentials(kind="sharepoint_oauth"))
    assert not r.ok


async def test_github_connect_requires_token() -> None:
    c = GitHubConnector()
    r = await c.connect(ConnectorCredentials(kind="github_pat", data={}))
    assert not r.ok
    assert "missing token" in r.detail


async def test_github_full_lifecycle() -> None:
    repo_listing = [
        {
            "full_name": "Bobcatsfan33/sovereign-platform",
            "default_branch": "main",
            "visibility": "public",
            "private": False,
        },
        {
            "full_name": "Bobcatsfan33/Aegis-",
            "default_branch": "main",
            "visibility": "private",
            "private": True,
        },
    ]
    file_payload = {
        "name": "README.md",
        "path": "README.md",
        "sha": "abc123",
        "size": 11,
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(b"hello world").decode(),
    }
    file_listing = [
        {"name": "README.md", "path": "README.md", "sha": "abc123", "size": 11, "type": "file"},
        {"name": "src", "path": "src", "sha": "def456", "type": "dir"},
    ]
    transport = _gh_handler(
        {
            "/user": {"body": {"login": "Bobcatsfan33"}},
            "/user/repos": {"body": repo_listing},
            "/repos/Bobcatsfan33/sovereign-platform/contents/": {"body": file_listing},
            "/repos/Bobcatsfan33/sovereign-platform/contents/README.md": {"body": file_payload},
            "/rate_limit": {"body": {"rate": {"remaining": 4999}}},
        }
    )

    conn = GitHubConnector(transport=transport)
    cr = await conn.connect(ConnectorCredentials(kind="github_pat", data={"token": "ghp_abc"}))
    assert cr.ok
    assert cr.principal == "Bobcatsfan33"

    # list repos
    repos = await conn.list_resources()
    assert {r.name for r in repos} == {
        "Bobcatsfan33/sovereign-platform",
        "Bobcatsfan33/Aegis-",
    }
    assert all(r.kind == "repository" for r in repos)

    # list contents of a repo
    contents = await conn.list_resources(
        {"repo": "Bobcatsfan33/sovereign-platform", "path": ""}
    )
    assert {c.name for c in contents} == {"README.md", "src"}

    # ingest one file -> S3 stage
    target = next(c for c in contents if c.name == "README.md")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket="sovereign-configs-test"
        )
        ir = await conn.ingest(
            target,
            IngestOptions(
                destination_bucket="sovereign-configs-test",
                destination_prefix="github/",
            ),
        )
        assert ir.ok, ir.detail
        assert ir.bytes_transferred == 11
        # Verify the file landed in S3
        obj = boto3.client("s3", region_name="us-east-1").get_object(
            Bucket="sovereign-configs-test",
            Key="github/Bobcatsfan33/sovereign-platform/README.md",
        )
        assert obj["Body"].read() == b"hello world"

    # health_check
    hs = await conn.health_check()
    assert hs.ok

    await conn.aclose()


async def test_github_list_org_repos() -> None:
    transport = _gh_handler(
        {
            "/user": {"body": {"login": "octocat"}},
            "/orgs/sovereign-gov/repos": {
                "body": [{"full_name": "sovereign-gov/platform", "private": False}]
            },
        }
    )
    conn = GitHubConnector(transport=transport)
    await conn.connect(ConnectorCredentials(kind="github_pat", data={"token": "x"}))
    repos = await conn.list_resources({"org": "sovereign-gov"})
    assert len(repos) == 1
    assert repos[0].name == "sovereign-gov/platform"


async def test_github_ingest_rejects_non_file_resource() -> None:
    conn = GitHubConnector(transport=_gh_handler({"/user": {"body": {"login": "x"}}}))
    await conn.connect(ConnectorCredentials(kind="github_pat", data={"token": "x"}))
    dir_resource = ResourceDescriptor(
        connector_type="github",
        resource_id="r@s:src",
        name="src",
        kind="dir",
        metadata={"repo": "o/r", "path": "src"},
    )
    ir = await conn.ingest(dir_resource, IngestOptions(destination_bucket="x"))
    assert not ir.ok
    assert "kind='file'" in ir.detail


async def test_github_health_check_when_not_connected() -> None:
    hs = await GitHubConnector().health_check()
    assert not hs.ok


async def test_github_ingest_rejects_oversize_file() -> None:
    large_content = base64.b64encode(b"x" * 100).decode()
    transport = _gh_handler(
        {
            "/user": {"body": {"login": "x"}},
            "/repos/o/r/contents/big.bin": {
                "body": {
                    "name": "big.bin",
                    "path": "big.bin",
                    "sha": "s",
                    "size": 100,
                    "type": "file",
                    "encoding": "base64",
                    "content": large_content,
                }
            },
        }
    )
    conn = GitHubConnector(transport=transport)
    await conn.connect(ConnectorCredentials(kind="github_pat", data={"token": "x"}))
    res = ResourceDescriptor(
        connector_type="github",
        resource_id="o/r@s:big.bin",
        name="big.bin",
        kind="file",
        metadata={"repo": "o/r", "path": "big.bin"},
    )
    with mock_aws():
        ir = await conn.ingest(
            res,
            IngestOptions(destination_bucket="x", max_size_bytes=10),
        )
    assert not ir.ok
    assert "exceeds max_size_bytes" in ir.detail


# Suppress unused-import noise
_ = json
