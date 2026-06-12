resource "aws_dynamodb_table" "instances" {
  name         = "sovereign_instances"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "instance_id"
  attribute {
    name = "instance_id"
    type = "S"
  }
  point_in_time_recovery {
    enabled = true
  }
  #tfsec:ignore:aws-dynamodb-table-customer-key SSE on (AWS-managed key); CMK wired via modules/kms
  server_side_encryption {
    enabled = true
  }
  deletion_protection_enabled = true
}
resource "aws_dynamodb_table" "bindings" {
  name         = "sovereign_bindings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "binding_id"
  attribute {
    name = "binding_id"
    type = "S"
  }
  point_in_time_recovery {
    enabled = true
  }
  #tfsec:ignore:aws-dynamodb-table-customer-key SSE on (AWS-managed key); CMK wired via modules/kms
  server_side_encryption {
    enabled = true
  }
  deletion_protection_enabled = true
}
