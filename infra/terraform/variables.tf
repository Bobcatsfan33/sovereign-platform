variable "region" { type = string default = "us-east-1" }
variable "config_bucket" { type = string default = "sovereign-configs-prod" }
variable "envoy_ami_id" { type = string }
variable "envoy_allowed_ingress_cidrs" { type = list(string) default = ["10.0.0.0/8"] }
variable "envoy_instance_type" { type = string default = "t3.small" }
variable "envoy_min_size" { type = number default = 2 }
variable "envoy_max_size" { type = number default = 6 }
variable "envoy_desired_capacity" { type = number default = 2 }
