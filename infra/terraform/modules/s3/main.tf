variable "bucket_name" { type = string }
resource "aws_s3_bucket" "configs" { bucket = var.bucket_name }
resource "aws_s3_bucket_versioning" "configs" {
  bucket = aws_s3_bucket.configs.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "configs" {
  bucket = aws_s3_bucket.configs.id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}
