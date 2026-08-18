# ANRA IAM Roles — IRSA for Bedrock + SSM + CloudWatch
# Import existing: terraform import aws_iam_role.anra AnraRole

variable "cluster_name" { default = "site-002-workload" }
variable "region" { default = "us-west-1" }
variable "account_id" { description = "AWS account ID" }
variable "oidc_issuer" { description = "EKS OIDC issuer URL (without https://)" }

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# ── IRSA Trust Policy ──
data "aws_iam_policy_document" "anra_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = ["arn:aws:iam::${var.account_id}:oidc-provider/${var.oidc_issuer}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_issuer}:sub"
      values   = ["system:serviceaccount:anra:anra-sa"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

# ── ANRA Role ──
resource "aws_iam_role" "anra" {
  name               = "AnraRole"
  assume_role_policy = data.aws_iam_policy_document.anra_trust.json
}

# ── Bedrock + SSM Policy ──
resource "aws_iam_role_policy" "anra_bedrock_ssm" {
  name = "AnraPolicy"
  role = aws_iam_role.anra.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = ["arn:aws:bedrock:*::foundation-model/*", "arn:aws:bedrock:*:*:inference-profile/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:SendCommand", "ssm:GetCommandInvocation", "ssm:DescribeInstanceInformation"]
        Resource = "*"
      },
    ]
  })
}

# ── CloudWatch Logs Read Policy ──
resource "aws_iam_role_policy" "anra_cloudwatch" {
  name = "AnraCloudWatchRead"
  role = aws_iam_role.anra.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:StartQuery", "logs:GetQueryResults", "logs:FilterLogEvents", "logs:DescribeLogGroups"]
      Resource = "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/containerinsights/*"
    }]
  })
}

output "anra_role_arn" { value = aws_iam_role.anra.arn }
