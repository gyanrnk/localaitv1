# ============================================================
# Phase 2 - Read-only data sources (networking + GPU AMI lookup)
# ============================================================
# terraform apply is MANUAL and GATED. Nothing here creates AWS
# resources; these are read-only lookups consumed by the Phase 2
# ECS-on-EC2 GPU builder stack.
#
# Networking: Phase 2 REUSES the DEFAULT VPC (vpc-0213982ec1cde401a)
# and its three ap-south-1a/b/c subnets. No new VPC / NAT / subnets
# are created.
#
# CRITICAL ap-south-1 SSM-param gap (audit (c)):
#   Neither
#     /aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id
#   nor the Amazon-Linux-2 equivalent RESOLVES in ap-south-1 - both
#   return ParameterNotFound. To keep `terraform plan`/`apply` from
#   hard-failing, the SSM data source below is GATED with `count` and
#   an operator can supply an explicit AMI id via var.ecs_gpu_ami_id.
#   See local.ecs_gpu_ami_id (coalesce of override -> SSM value).
#   README documents how to find the latest ECS GPU AL2023 AMI id.
#
# NOTE: data.aws_caller_identity.current is already declared in oidc.tf
#       and is REFERENCED (not redeclared) by the Phase 2 files.
# ============================================================

# --- Default VPC (vpc-0213982ec1cde401a) ---
data "aws_vpc" "default" {
  default = true
}

# --- The three default subnets (ap-south-1a/b/c) in the default VPC ---
# Used as the ASG vpc_zone_identifier and the ECS service network.
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# --- ECS GPU AMI via SSM (gated; may not resolve in ap-south-1) ---
# Only queried when no explicit override (var.ecs_gpu_ami_id) is given.
# `try(...)` on the value below means a ParameterNotFound at plan time
# still surfaces - but if the operator passes ecs_gpu_ami_id the data
# source is never instantiated (count = 0), so plan/apply succeeds.
data "aws_ssm_parameter" "ecs_gpu_ami" {
  count = var.ecs_gpu_ami_id == "" ? 1 : 0
  name  = var.ecs_gpu_ami_ssm_param
}

locals {
  # Operator override wins; otherwise fall back to the SSM value if it
  # resolved. In ap-south-1 the SSM path is expected to be empty, so
  # ecs_gpu_ami_id MUST be supplied explicitly (validated in asg.tf via
  # the launch template - an empty image_id is rejected at apply time).
  ecs_gpu_ami_id = coalesce(
    var.ecs_gpu_ami_id,
    try(data.aws_ssm_parameter.ecs_gpu_ami[0].value, "")
  )
}
