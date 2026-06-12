# infra/terraform/backend.tf — remote state with locking (was: local state).
# Local Terraform state in a platform that runs terraform-apply for tenants is
# a non-starter: state holds secrets and unlocked state corrupts under
# concurrency. Bucket / region / lock table are supplied at init via
# -backend-config (they can't be variables in a backend block), e.g.:
#
#   terraform init \
#     -backend-config="bucket=sovereign-tf-state-<account_id>" \
#     -backend-config="region=us-gov-west-1" \
#     -backend-config="dynamodb_table=sovereign-tf-locks"
terraform {
  backend "s3" {
    key     = "platform/terraform.tfstate"
    encrypt = true
  }
}
