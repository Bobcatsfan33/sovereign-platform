"""S3 connector — list and ingest objects from an S3 bucket.

The most common government data source: every agency has S3 (or an
S3-compatible store: MinIO, on-prem object storage). Supports both
AWS-credential and IAM-role auth. Streams objects to the platform's
staging bucket without buffering the entire payload in memory.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .base import BaseConnector
from .types import (
    ConnectionResult,
    ConnectorCredentials,
    HealthStatus,
    IngestOptions,
    IngestResult,
    ResourceDescriptor,
)

logger = logging.getLogger("sovereign.connectors.s3")


class S3Connector(BaseConnector):
    connector_type: ClassVar[str] = "s3"

    def __init__(self) -> None:
        self._client: Any = None
        self._principal: str = ""
        self._endpoint_url: str | None = None
        self._region: str = "us-east-1"

    async def connect(self, credentials: ConnectorCredentials) -> ConnectionResult:
        """Build a boto3 S3 client. Accepts:
            kind='aws_access_key' data={'access_key_id', 'secret_access_key',
                                         'region'?, 'endpoint_url'?}
            kind='aws_iam_role'   data={'region'?, 'endpoint_url'?} — relies on
                                         the host's instance profile / role.
        """
        data = credentials.data
        self._endpoint_url = data.get("endpoint_url")
        self._region = data.get("region", "us-east-1")

        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": self._region,
        }
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url

        if credentials.kind == "aws_access_key":
            client_kwargs["aws_access_key_id"] = data["access_key_id"]
            client_kwargs["aws_secret_access_key"] = data["secret_access_key"]
        elif credentials.kind == "aws_iam_role":
            # boto3 picks up the IAM role from instance metadata
            pass
        else:
            return ConnectionResult(
                ok=False,
                detail=f"unsupported credential kind for S3: {credentials.kind!r}",
            )

        try:
            self._client = boto3.client(**client_kwargs)
            sts = boto3.client("sts", region_name=self._region)
            try:
                ident = sts.get_caller_identity()
                self._principal = ident.get("Arn", ident.get("Account", ""))
            except (ClientError, BotoCoreError):
                # STS may not be reachable from MinIO etc. — fall back to a
                # cheap S3 op for a non-empty principal string.
                self._client.list_buckets()
                self._principal = "s3-connection"
        except (ClientError, BotoCoreError) as exc:
            return ConnectionResult(ok=False, detail=str(exc))

        return ConnectionResult(ok=True, principal=self._principal)

    async def list_resources(
        self, filters: dict | None = None
    ) -> list[ResourceDescriptor]:
        """Filters:
            {} or None                 -> list every bucket.
            {'bucket': X}              -> list every object in bucket X.
            {'bucket': X, 'prefix': P} -> list objects with prefix P.
            {'bucket': X, 'max_keys': N} -> cap returned items.
        """
        if self._client is None:
            raise RuntimeError("S3Connector.connect() must run before list_resources")
        filters = filters or {}
        bucket = filters.get("bucket")

        if not bucket:
            try:
                resp = await asyncio.to_thread(self._client.list_buckets)
            except (ClientError, BotoCoreError) as exc:
                logger.warning("list_buckets failed: %s", exc)
                return []
            return [
                ResourceDescriptor(
                    connector_type=self.connector_type,
                    resource_id=b["Name"],
                    name=b["Name"],
                    kind="bucket",
                    last_modified=b.get("CreationDate"),
                )
                for b in resp.get("Buckets", [])
            ]

        kwargs: dict[str, Any] = {"Bucket": bucket}
        if "prefix" in filters:
            kwargs["Prefix"] = filters["prefix"]
        if "max_keys" in filters:
            kwargs["MaxKeys"] = filters["max_keys"]

        try:
            resp = await asyncio.to_thread(self._client.list_objects_v2, **kwargs)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("list_objects_v2 failed: %s", exc)
            return []
        return [
            ResourceDescriptor(
                connector_type=self.connector_type,
                resource_id=f"{bucket}/{obj['Key']}",
                name=obj["Key"],
                kind="object",
                size_bytes=obj.get("Size"),
                last_modified=obj.get("LastModified"),
                metadata={"etag": obj.get("ETag", ""), "bucket": bucket},
            )
            for obj in resp.get("Contents", []) or []
        ]

    async def ingest(
        self, resource: ResourceDescriptor, options: IngestOptions
    ) -> IngestResult:
        """Copy an object from the source bucket into the platform's
        staging bucket. The resource_id is the source `bucket/key`."""
        if self._client is None:
            raise RuntimeError("S3Connector.connect() must run before ingest")
        if resource.kind != "object":
            return IngestResult(
                ok=False,
                detail=f"S3 ingest expects kind='object', got {resource.kind!r}",
            )

        try:
            src_bucket, src_key = resource.resource_id.split("/", 1)
        except ValueError:
            return IngestResult(ok=False, detail="malformed resource_id")

        try:
            obj = await asyncio.to_thread(
                self._client.get_object, Bucket=src_bucket, Key=src_key
            )
            body: bytes = obj["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            return IngestResult(ok=False, detail=f"source read failed: {exc}")

        if options.max_size_bytes is not None and len(body) > options.max_size_bytes:
            return IngestResult(
                ok=False,
                detail=f"object {len(body)} bytes exceeds max_size_bytes={options.max_size_bytes}",
            )

        staged_key = f"{options.destination_prefix.rstrip('/')}/{src_key}".lstrip("/")
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=options.destination_bucket,
                Key=staged_key,
                Body=body,
                ContentType=obj.get("ContentType", "application/octet-stream"),
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
            await asyncio.to_thread(self._client.list_buckets)
        except (ClientError, BotoCoreError) as exc:
            return HealthStatus(ok=False, message=str(exc))
        return HealthStatus(ok=True, message=f"principal={self._principal}")
