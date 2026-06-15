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

# ============================================================
# Input variables (Phase 2 - GPU builder: ECS-on-EC2 + SQS)
# ============================================================

variable "ecs_gpu_ami_ssm_param" {
  description = <<-EOT
    SSM parameter name for the ECS GPU-optimized AMI (AL2023). NOTE: this
    parameter does NOT resolve in ap-south-1 (audit (c): ParameterNotFound),
    so in this region you MUST supply ecs_gpu_ami_id explicitly. The data
    source that reads this is gated and skipped when ecs_gpu_ami_id is set.
  EOT
  type        = string
  default     = "/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id"
}

variable "ecs_gpu_ami_id" {
  description = <<-EOT
    Explicit ECS GPU-optimized AMI id override. REQUIRED in ap-south-1
    where the SSM param above does not resolve (audit (c)). Leave empty
    only in a region where the SSM param resolves. See README for how to
    find the latest ECS GPU AL2023 AMI id.
  EOT
  type        = string
  default     = ""
}

variable "builder_instance_type" {
  description = "EC2 instance type for GPU builders (one builder task per host)."
  type        = string
  default     = "g4dn.xlarge"
}

variable "asg_max" {
  description = <<-EOT
    Max number of concurrent g4dn.xlarge builders (ASG max_size and
    appautoscaling max_capacity). Bounded by the On-Demand G/VT vCPU quota
    (audit (b): 8 vCPU, service ec2, quota L-DB2E81BA). g4dn.xlarge = 4
    vCPU, so floor(8 / 4) = 2. Raise the quota (L-DB2E81BA) AND this value
    together for more parallelism.
  EOT
  type        = number
  default     = 2
}

variable "builder_root_volume_gb" {
  description = "Root EBS volume size (GiB) for builder instances (GPU image layers + video scratch)."
  type        = number
  default     = 100
}

variable "builder_image_tag" {
  description = "Tag of the builder image in ECR to run (laitv-stg-builder:<tag>)."
  type        = string
  default     = "latest"
}

variable "builder_command" {
  description = <<-EOT
    Container command for the builder task. PHASE 3 PLACEHOLDER: this is
    ["python", "worker.py"], where worker.py is the Phase 3 SQS consumer
    that has NOT yet been written. The task is not runnable until Phase 3
    ships worker.py into the image.
  EOT
  type        = list(string)
  default     = ["python", "worker.py"]
}

variable "builder_secret_keys" {
  description = <<-EOT
    Secret keys resolved from SSM Parameter Store at container start, under
    the path prefix /localaitv/<env>/<key>. Wired into the task definition
    `secrets` valueFrom for the Phase 3 worker.
  EOT
  type        = list(string)
  default     = ["OPENAI_API_KEY", "DATABASE_URL", "S3_BUCKET_NAME"]
}

variable "s3_bucket_arns" {
  description = <<-EOT
    App S3 bucket ARNs the builder task role may access (Get/Put/Delete
    object + ListBucket). Empty list (default) disables the S3 statements
    in the task role policy.
  EOT
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "CloudWatch log retention (days) for the builder log group."
  type        = number
  default     = 30
}

variable "enable_container_insights" {
  description = "Enable ECS Container Insights on the builder cluster (off by default to save cost)."
  type        = bool
  default     = false
}
