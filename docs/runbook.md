# Operations Runbook

## Provision failed

1. Check broker logs.
2. Confirm DynamoDB table health.
3. Check control-plane `/healthz`.
4. Verify MinIO/S3 bucket exists.
5. Retry provision; operation is idempotent for existing instances.

## Bad Envoy config

1. Fetch the generated artifact from S3/MinIO.
2. Run `envoy --mode validate -c envoy.yaml`.
3. Patch service instance with a corrected route or cluster definition.
4. Roll back by binding Envoy to the previous config version.

## Audit review

Query ClickHouse:

```sql
SELECT * FROM sovereign.events ORDER BY ts DESC LIMIT 50;
```
