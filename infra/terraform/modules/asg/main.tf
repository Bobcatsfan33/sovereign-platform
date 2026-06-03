variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "ami_id" { type = string }
variable "allowed_ingress_cidrs" { type = list(string) default = ["10.0.0.0/8"] }
variable "instance_type" { type = string default = "t3.small" }
variable "min_size" { type = number default = 2 }
variable "max_size" { type = number default = 6 }
variable "desired_capacity" { type = number default = 2 }

resource "aws_security_group" "envoy" {
  name = "sovereign-envoy"
  vpc_id = var.vpc_id
  ingress { from_port = 80 to_port = 8443 protocol = "tcp" cidr_blocks = var.allowed_ingress_cidrs }
  egress { from_port = 0 to_port = 0 protocol = "-1" cidr_blocks = ["0.0.0.0/0"] }
}
resource "aws_launch_template" "envoy" {
  name_prefix = "sovereign-envoy-"
  image_id = var.ami_id
  instance_type = var.instance_type
  vpc_security_group_ids = [aws_security_group.envoy.id]
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      encrypted   = true
      volume_size = 20
      volume_type = "gp3"
    }
  }
}
resource "aws_autoscaling_group" "envoy" {
  min_size = var.min_size
  max_size = var.max_size
  desired_capacity = var.desired_capacity
  vpc_zone_identifier = var.subnet_ids
  launch_template { id = aws_launch_template.envoy.id version = "$Latest" }
  tag {
    key                 = "Name"
    value               = "sovereign-envoy"
    propagate_at_launch = true
  }
}
