# ============================================================
# Phase 2 - CloudWatch log group for the builder task
# ============================================================
# terraform apply is MANUAL and GATED.
#
# Referenced by:
#   - builder_service.tf : the task definition's awslogs logConfiguration
#     (awslogs-group + awslogs-region = var.aws_region + stream-prefix
#     "builder").
#   - iam.tf : the task-exec role's logs:CreateLogStream/PutLogEvents
#     permissions are scoped to this group.
# ============================================================

resource "aws_cloudwatch_log_group" "builder" {
  name              = "/ecs/laitv-${var.env}-builder"
  retention_in_days = var.log_retention_days
}
