# ============================================================
# Input variables (Phase 1)
# ============================================================

variable "aws_region" {
  description = "AWS region for all Phase 1 resources."
  type        = string
  default     = "ap-south-1"
}

variable "env" {
  description = "Environment short name, used in resource prefixes (laitv-<env>-*)."
  type        = string
  default     = "stg"
}

variable "ecr_repository_name" {
  description = "Name of the ECR repository for the GPU builder image."
  type        = string
  default     = "laitv-stg-builder"
}

variable "untagged_image_expiry_days" {
  description = "Number of days after which untagged ECR images are expired by the lifecycle policy."
  type        = number
  default     = 14
}

variable "github_owner" {
  description = "GitHub org/user that owns the repo allowed to assume the OIDC role."
  type        = string
  default     = "gyanrnk"
}

variable "github_repo" {
  description = "GitHub repository name allowed to assume the OIDC role."
  type        = string
  default     = "localaitv1"
}

variable "create_oidc_provider" {
  description = <<-EOT
    Whether to CREATE the GitHub OIDC provider. The provider
    (token.actions.githubusercontent.com) already exists in account
    689186650531 (created 2026-02-06), so this defaults to false and the
    existing provider is referenced via a data source instead. Set to true
    only in an account where the provider does not yet exist.
  EOT
  type        = bool
  default     = false
}
