#tfsec:ignore:aws-ec2-require-vpc-flow-logs-for-all-vpcs flow logs provisioned by the landing zone
resource "aws_vpc" "this" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
}
resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(aws_vpc.this.cidr_block, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
}
data "aws_availability_zones" "available" {
  state = "available"
}
output "vpc_id" {
  value = aws_vpc.this.id
}
output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}
