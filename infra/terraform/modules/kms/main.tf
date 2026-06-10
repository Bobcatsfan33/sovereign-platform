# Customer-managed KMS key for encryption at rest, with automatic annual key
# rotation enabled (WS2 data-durability). Used to encrypt the state store, the
# artifact bucket, and audit storage rather than relying on AWS-managed keys.

variable "alias" {
  type    = string
  default = "alias/sovereign-platform"
}

variable "deletion_window_in_days" {
  type    = number
  default = 30
}

resource "aws_kms_key" "this" {
  description             = "Sovereign Platform CMK for encryption at rest"
  enable_key_rotation     = true
  deletion_window_in_days = var.deletion_window_in_days
}

resource "aws_kms_alias" "this" {
  name          = var.alias
  target_key_id = aws_kms_key.this.key_id
}

output "key_arn" {
  value = aws_kms_key.this.arn
}

output "key_id" {
  value = aws_kms_key.this.key_id
}
