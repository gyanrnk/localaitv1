# ============================================================
# Phase 2 - Outputs (GPU builder stack)
# ============================================================
# terraform apply is MANUAL and GATED.
#
# NEW dedicated outputs file. Phase 1 outputs remain inline in oidc.tf
# (github_ecr_push_role_arn, ecr_repository_url) and are NOT moved here.
# These outputs feed the Phase 3 worker configuration and ops runbooks.
# ============================================================

output "ecs_cluster_name" {
  description = "Name of the ECS-on-EC2 GPU builder cluster."
  value       = aws_ecs_cluster.builders.name
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS-on-EC2 GPU builder cluster."
  value       = aws_ecs_cluster.builders.arn
}

output "build_queue_url" {
  description = "URL of the FIFO build job queue (SQS_BUILD_QUEUE_URL for the worker)."
  value       = aws_sqs_queue.build.url
}

output "build_queue_arn" {
  description = "ARN of the FIFO build job queue."
  value       = aws_sqs_queue.build.arn
}

output "build_dlq_url" {
  description = "URL of the FIFO build dead-letter queue."
  value       = aws_sqs_queue.build_dlq.url
}

output "builder_asg_name" {
  description = "Name of the builder Auto Scaling Group."
  value       = aws_autoscaling_group.builder.name
}

output "builder_capacity_provider_name" {
  description = "Name of the ECS capacity provider backing the builder ASG."
  value       = aws_ecs_capacity_provider.builder.name
}

output "builder_service_name" {
  description = "Name of the builder ECS service."
  value       = aws_ecs_service.builder.name
}

output "builder_task_definition_arn" {
  description = "ARN of the builder task definition (most recent revision)."
  value       = aws_ecs_task_definition.builder.arn
}

output "builder_log_group_name" {
  description = "CloudWatch log group for the builder task."
  value       = aws_cloudwatch_log_group.builder.name
}
