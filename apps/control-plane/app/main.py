from fastapi import FastAPI, HTTPException
import boto3
from botocore.exceptions import ClientError
from sovereign.models import RenderRequest
from sovereign.render import render_envoy
from sovereign.settings import get_settings
from sovereign.audit import Audit

app = FastAPI(title="Sovereign Envoy Control Plane", version="0.1.0")
audit = Audit()

@app.on_event("startup")
def startup():
    s = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.aws_region,
    )
    try:
        client.head_bucket(Bucket=s.config_bucket)
    except ClientError:
        client.create_bucket(Bucket=s.config_bucket)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.post("/render")
def render(req: RenderRequest):
    s = get_settings()
    body = render_envoy(req.instance)
    key = f"instances/{req.instance.instance_id}/v{req.instance.version}/envoy.yaml"
    s3 = boto3.client("s3", endpoint_url=s.s3_endpoint, aws_access_key_id=s.s3_access_key, aws_secret_access_key=s.s3_secret_key, region_name=s.aws_region)
    s3.put_object(Bucket=s.config_bucket, Key=key, Body=body.encode(), ContentType="application/x-yaml")
    audit.emit("config.rendered", req.instance.instance_id, key)
    return {"bucket": s.config_bucket, "key": key, "version": req.instance.version}

@app.get("/instances/{instance_id}/versions/{version}/envoy.yaml")
def get_config(instance_id: str, version: int):
    s = get_settings()
    key = f"instances/{instance_id}/v{version}/envoy.yaml"
    s3 = boto3.client("s3", endpoint_url=s.s3_endpoint, aws_access_key_id=s.s3_access_key, aws_secret_access_key=s.s3_secret_key, region_name=s.aws_region)
    try:
        obj = s3.get_object(Bucket=s.config_bucket, Key=key)
        return obj["Body"].read().decode()
    except ClientError as e:
        raise HTTPException(status_code=404, detail=str(e))
