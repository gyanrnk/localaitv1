# ============================================================
# Phase 2 - Application Auto Scaling on the builder service (SQS depth)
# ============================================================
# terraform apply is MANUAL and GATED.
#
# Scales the ECS service desired_count between 0 and var.asg_max based on
# the build queue depth (AWS/SQS ApproximateNumberOfMessagesVisible):
#   - >= 1 visible message  -> scale OUT (add a builder task; the ECS
#     managed-scaling capacity provider then launches a g4dn.xlarge).
#   - == 0 visible messages -> scale IN to 0 (tasks stop; the capacity
#     provider drains the ASG back to 0 -> near-zero idle cost).
#
# Pairs with the ECS managed-scaling capacity provider (asg.tf): app
# autoscaling controls how many builder TASKS are wanted; the capacity
# provider supplies/removes the EC2 capacity to run them.
# ============================================================

resource "aws_appautoscaling_target" "builder" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.builders.name}/${aws_ecs_service.builder.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = 0
  max_capacity       = var.asg_max
}

# --- Scale OUT: add one builder task when work is queued ---
resource "aws_appautoscaling_policy" "scale_out" {
  name               = "laitv-${var.env}-builder-scale-out"
  service_namespace  = aws_appautoscaling_target.builder.service_namespace
  resource_id        = aws_appautoscaling_target.builder.resource_id
  scalable_dimension = aws_appautoscaling_target.builder.scalable_dimension
  policy_type        = "StepScaling"

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 60
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 1
    }
  }
}

# --- Scale IN: drain to 0 when the queue is empty ---
resource "aws_appautoscaling_policy" "scale_in" {
  name               = "laitv-${var.env}-builder-scale-in"
  service_namespace  = aws_appautoscaling_target.builder.service_namespace
  resource_id        = aws_appautoscaling_target.builder.resource_id
  scalable_dimension = aws_appautoscaling_target.builder.scalable_dimension
  policy_type        = "StepScaling"

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 300
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = 0
    }
  }
}

# --- Alarm: queue has work -> scale out ---
resource "aws_cloudwatch_metric_alarm" "build_queue_high" {
  alarm_name          = "laitv-${var.env}-build-queue-high"
  alarm_description   = "Build queue has >= 1 visible message; scale the builder service out."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  period              = 60
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.build.name
  }

  alarm_actions = [aws_appautoscaling_policy.scale_out.arn]
}

# --- Alarm: queue empty -> scale in to 0 ---
resource "aws_cloudwatch_metric_alarm" "build_queue_empty" {
  alarm_name          = "laitv-${var.env}-build-queue-empty"
  alarm_description   = "Build queue has 0 visible messages; drain the builder service to 0."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  comparison_operator = "LessThanOrEqualToThreshold"
  threshold           = 0
  period              = 60
  evaluation_periods  = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.build.name
  }

  alarm_actions = [aws_appautoscaling_policy.scale_in.arn]
}
