variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "ami_id" { type = string }
resource "aws_security_group" "envoy" {
  name = "sovereign-envoy"
  vpc_id = var.vpc_id
  ingress { from_port = 80 to_port = 8443 protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }
  egress { from_port = 0 to_port = 0 protocol = "-1" cidr_blocks = ["0.0.0.0/0"] }
}
resource "aws_launch_template" "envoy" {
  name_prefix = "sovereign-envoy-"
  image_id = var.ami_id
  instance_type = "t3.small"
  vpc_security_group_ids = [aws_security_group.envoy.id]
}
resource "aws_autoscaling_group" "envoy" {
  min_size = 2
  max_size = 6
  desired_capacity = 2
  vpc_zone_identifier = var.subnet_ids
  launch_template { id = aws_launch_template.envoy.id version = "$Latest" }
}
