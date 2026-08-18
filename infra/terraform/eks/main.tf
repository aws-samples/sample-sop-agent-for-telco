# EKS Cluster + Node Groups + Add-ons
# Import existing: terraform import aws_eks_cluster.this site-002-workload

variable "cluster_name" { default = "site-002-workload" }
variable "region" { default = "us-west-1" }
variable "vpc_id" { description = "Existing VPC ID" }
variable "subnet_ids" { description = "Subnet IDs for EKS" type = list(string) }
variable "node_role_arn" { description = "IAM role ARN for node groups" }

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# ── EKS Cluster ──
resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = var.node_role_arn
  version  = "1.32"

  vpc_config {
    subnet_ids = var.subnet_ids
  }
}

# ── Managed Node Group (region EC2) ──
resource "aws_eks_node_group" "region" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.cluster_name}-region"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.subnet_ids
  instance_types  = ["t3.medium"]

  scaling_config {
    desired_size = 4
    max_size     = 6
    min_size     = 2
  }

  labels = { role = "region" }
}

# ── EKS Add-ons ──
resource "aws_eks_addon" "cloudwatch" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "amazon-cloudwatch-observability"
}

# ── Outputs ──
output "cluster_endpoint" { value = aws_eks_cluster.this.endpoint }
output "cluster_ca" { value = aws_eks_cluster.this.certificate_authority[0].data }
output "oidc_issuer" { value = aws_eks_cluster.this.identity[0].oidc[0].issuer }
