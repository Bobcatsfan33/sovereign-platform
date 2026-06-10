variable "region" { type = string default = "us-east-1" }
variable "config_bucket" { type = string default = "sovereign-configs-prod" }
variable "envoy_ami_id" { type = string }
variable "envoy_allowed_ingress_cidrs" { type = list(string) default = ["10.0.0.0/8"] }
variable "envoy_instance_type" { type = string default = "t3.small" }
variable "envoy_min_size" { type = number default = 2 }
variable "envoy_max_size" { type = number default = 6 }
variable "envoy_desired_capacity" { type = number default = 2 }

# Least-privilege IAM (WS2) — operator supplies the cluster OIDC provider and
# the resource ARNs the per-service roles are scoped to.
variable "oidc_provider_arn" {
  type    = string
  default = ""
}
variable "oidc_provider_url" {
  type    = string
  default = ""
}
variable "instances_table_arn" {
  type    = string
  default = ""
}
variable "bindings_table_arn" {
  type    = string
  default = ""
}
variable "config_bucket_arn" {
  type    = string
  default = ""
}
