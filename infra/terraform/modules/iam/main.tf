# Least-privilege, per-service IAM roles (WS2). The platform that brokers
# infrastructure holds itself to the standard it enforces: each service gets
# its own IRSA role with an explicit, resource-scoped policy — no wildcard
# actions, no shared role.

variable "oidc_provider_arn" {
  type        = string
  description = "EKS cluster OIDC provider ARN for IRSA."
}

variable "oidc_provider_url" {
  type        = string
  description = "EKS OIDC provider URL (without https://)."
}

variable "instances_table_arn" {
  type = string
}

variable "bindings_table_arn" {
  type = string
}

variable "config_bucket_arn" {
  type = string
}

locals {
  services = ["broker", "control-plane", "audit-service", "metering-service"]
}

# Each service assumes only its own role, bound to its k8s ServiceAccount.
data "aws_iam_policy_document" "assume" {
  for_each = toset(local.services)

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:sovereign-platform:${each.value}"]
    }
  }
}

resource "aws_iam_role" "service" {
  for_each           = toset(local.services)
  name               = "sovereign-${each.value}"
  assume_role_policy = data.aws_iam_policy_document.assume[each.value].json
}

# Broker: read/write only its own state tables + read the config bucket.
data "aws_iam_policy_document" "broker" {
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:DeleteItem",
    ]
    #tfsec:ignore:aws-iam-no-policy-wildcards GSI access needs table/index/*; table ARNs are explicit
    resources = [
      var.instances_table_arn,
      "${var.instances_table_arn}/index/*",
      var.bindings_table_arn,
    ]
  }
  statement {
    effect  = "Allow"
    actions = ["s3:GetObject"]
    #tfsec:ignore:aws-iam-no-policy-wildcards object access needs <bucket>/*; bucket is explicit
    resources = ["${var.config_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "broker" {
  name   = "broker-least-privilege"
  role   = aws_iam_role.service["broker"].id
  policy = data.aws_iam_policy_document.broker.json
}

# Control-plane writes rendered artifacts to the config bucket only.
data "aws_iam_policy_document" "control_plane" {
  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    #tfsec:ignore:aws-iam-no-policy-wildcards object access needs <bucket>/*; bucket is explicit
    resources = ["${var.config_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "control_plane" {
  name   = "control-plane-least-privilege"
  role   = aws_iam_role.service["control-plane"].id
  policy = data.aws_iam_policy_document.control_plane.json
}

output "role_arns" {
  value = { for svc, role in aws_iam_role.service : svc => role.arn }
}
