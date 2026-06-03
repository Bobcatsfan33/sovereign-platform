# Deployment Hardening

Sprint 3 turns the deployment surface from local examples into reviewable
production artifacts. It does not perform the first production deployment.

## Kubernetes

`deploy/k8s/production.yaml` covers the full chassis:

- broker
- control plane
- audit service
- metering service
- portal
- OPA

The manifest set includes:

- restricted Pod Security labels
- dedicated service accounts
- service-account token automount disabled
- pod and container security contexts
- dropped Linux capabilities
- readiness and liveness probes
- resource requests and limits
- default-deny network policy plus constrained internal/DNS/HTTPS egress
- non-`:latest` images

Environment-specific overlays must replace placeholder OIDC values, workload
identity allow-lists, IRSA role ARNs, image tags/digests, OPA policy ConfigMap
content, and ingress/TLS resources.

## Terraform

The AWS modules now include baseline hardening:

- S3 config artifacts use KMS encryption, bucket keys, versioning, block public
  access, and bucket-owner-enforced ownership.
- DynamoDB state tables enable point-in-time recovery, server-side encryption,
  and deletion protection.
- Envoy ASG ingress is not open to the world by default.
- Envoy launch templates require IMDSv2 and encrypted gp3 root volumes.

Before production use, agencies must still add environment-specific IAM
policies, private endpoints, CloudWatch/SIEM routing, backup schedules,
multi-region DR, and approval workflows.
