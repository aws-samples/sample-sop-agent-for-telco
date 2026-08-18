terraform {
  required_version = ">= 1.3"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  # CloudFront is a global API; you may use a single region (e.g. us-east-1) for this stack.
  region = var.aws_region
}
