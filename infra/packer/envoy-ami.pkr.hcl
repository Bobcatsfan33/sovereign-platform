packer {
  required_plugins { amazon = { version = ">= 1.2.0", source = "github.com/hashicorp/amazon" } }
}
variable "region" { default = "us-east-1" }
source "amazon-ebs" "envoy" {
  region = var.region
  instance_type = "t3.small"
  source_ami_filter { filters = { name = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" } owners = ["099720109477"] most_recent = true }
  ssh_username = "ubuntu"
  ami_name = "sovereign-envoy-{{timestamp}}"
}
build {
  sources = ["source.amazon-ebs.envoy"]
  provisioner "shell" { inline = ["sudo apt-get update", "sudo apt-get install -y curl gnupg python3-pip"] }
  provisioner "shell" { inline = ["curl -L https://func-e.io/install.sh | bash -s -- -b /usr/local/bin", "func-e use 1.30.0 || true"] }
}
