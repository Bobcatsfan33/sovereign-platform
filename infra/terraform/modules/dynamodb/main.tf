resource "aws_dynamodb_table" "instances" {
  name = "sovereign_instances"
  billing_mode = "PAY_PER_REQUEST"
  hash_key = "instance_id"
  attribute { name = "instance_id" type = "S" }
}
resource "aws_dynamodb_table" "bindings" {
  name = "sovereign_bindings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key = "binding_id"
  attribute { name = "binding_id" type = "S" }
}
