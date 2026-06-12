terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
}

provider "aws" { region = var.region }

module "kms" { source = "./modules/kms" }
module "iam" {
  source              = "./modules/iam"
  oidc_provider_arn   = var.oidc_provider_arn
  oidc_provider_url   = var.oidc_provider_url
  instances_table_arn = var.instances_table_arn
  bindings_table_arn  = var.bindings_table_arn
  config_bucket_arn   = var.config_bucket_arn
}
module "state" { source = "./modules/dynamodb" }
module "artifacts" {
  source      = "./modules/s3"
  bucket_name = var.config_bucket
}
module "network" { source = "./modules/network" }
module "envoy_asg" {
  source                = "./modules/asg"
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.private_subnet_ids
  ami_id                = var.envoy_ami_id
  allowed_ingress_cidrs = var.envoy_allowed_ingress_cidrs
  instance_type         = var.envoy_instance_type
  min_size              = var.envoy_min_size
  max_size              = var.envoy_max_size
  desired_capacity      = var.envoy_desired_capacity
}
