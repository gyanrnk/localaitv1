# ============================================================
# Terraform providers & backend (Phase 1 — ECR + OIDC only)
# ============================================================
# Region: ap-south-1 (Mumbai). Staging environment.
#
# Backend is intentionally LOCAL for Phase 1 so that nothing is
# created or written remotely until an operator explicitly runs
# `terraform apply` (see README.md). Switch to an S3 backend in a
# later phase if remote state is desired.
# ============================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "localaitv"
      Env       = var.env
      ManagedBy = "terraform"
      Phase     = "phase1-ecr-oidc"
    }
  }
}
