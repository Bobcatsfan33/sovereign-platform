variable "bucket_name" {
  type = string
}
variable "kms_deletion_window_in_days" {
  type    = number
  default = 30
}

resource "aws_kms_key" "configs" {
  description             = "Sovereign Platform config artifact encryption"
  deletion_window_in_days = var.kms_deletion_window_in_days
  enable_key_rotation     = true
}

resource "aws_kms_alias" "configs" {
  name          = "alias/sovereign-config-artifacts"
  target_key_id = aws_kms_key.configs.key_id
}

#tfsec:ignore:aws-s3-enable-bucket-logging access logging targets an env-specific archive bucket
resource "aws_s3_bucket" "configs" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_public_access_block" "configs" {
  bucket                  = aws_s3_bucket.configs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "configs" {
  bucket = aws_s3_bucket.configs.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_versioning" "configs" {
  bucket = aws_s3_bucket.configs.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "configs" {
  bucket = aws_s3_bucket.configs.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.configs.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "configs" {
  bucket = aws_s3_bucket.configs.id
  rule {
    id     = "retain-versioned-configs"
    status = "Enabled"
    noncurrent_version_expiration { noncurrent_days = 3650 }
  }
}

output "bucket_name" { value = aws_s3_bucket.configs.bucket }
output "kms_key_arn" { value = aws_kms_key.configs.arn }
