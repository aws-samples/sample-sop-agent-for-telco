terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "cluster_name" { default = "anra-workshop" }
variable "region" { default = "ap-northeast-1" }
variable "vpc_id" { description = "VPC ID from CFN" }
variable "private_subnets" { type = list(string) }

provider "aws" { region = var.region }

# ── EKS Cluster ──
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.31"
  vpc_id          = var.vpc_id
  subnet_ids      = var.private_subnets

  cluster_endpoint_public_access = true
  enable_cluster_creator_admin_permissions = true

  cluster_addons = {
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
  }

  eks_managed_node_groups = {
    workshop = {
      instance_types = ["m5.xlarge"]
      min_size       = 2
      max_size       = 4
      desired_size   = 3
      labels         = { role = "region" }
    }
  }
}

# ── EBS CSI IRSA ──
module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name             = "${var.cluster_name}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }
}

# ── ANRA IRSA (Bedrock + SSM) ──
module "anra_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${var.cluster_name}-anra"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["anra:anra-sa"]
    }
  }

  role_policy_arns = { anra = aws_iam_policy.anra.arn }
}

resource "aws_iam_policy" "anra" {
  name = "${var.cluster_name}-anra"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = ["arn:aws:bedrock:*::foundation-model/*", "arn:aws:bedrock:*:*:inference-profile/*"]
      }
    ]
  })
}

output "cluster_name" { value = module.eks.cluster_name }
output "cluster_endpoint" { value = module.eks.cluster_endpoint }
output "anra_role_arn" { value = module.anra_irsa.iam_role_arn }
output "configure_kubectl" { value = "aws eks update-kubeconfig --name ${var.cluster_name} --region ${var.region}" }
