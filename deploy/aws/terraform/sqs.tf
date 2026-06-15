# ============================================================
# Phase 2 - Build job queue + dead-letter queue (both FIFO)
# ============================================================
# terraform apply is MANUAL and GATED.
#
# The build queue carries one message per video-build job. The Phase 3
# SQS worker (worker.py - NOT yet written) consumes from this queue on a
# g4dn.xlarge launched by the ECS managed-scaling capacity provider.
#
# FIFO is used so build jobs are processed in submission order and
# de-duplicated. visibility_timeout_seconds (1800s = 30 min) matches the
# builder task max runtime so an in-flight job is not re-delivered while a
# builder is still working on it. Failed jobs (maxReceiveCount = 3) are
# parked in the DLQ for inspection.
#
# Tags inherit from the provider default_tags block (providers.tf).
# Consumed by: builder_service.tf (task env + task-role policy) and
#              autoscaling.tf (CloudWatch SQS depth metric).
# ============================================================

# --- Dead-letter queue (FIFO) ---
resource "aws_sqs_queue" "build_dlq" {
  name                        = "laitv-${var.env}-build-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days - max retention for inspection
}

# --- Build job queue (FIFO) ---
resource "aws_sqs_queue" "build" {
  name                        = "laitv-${var.env}-build.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 1800 # 30 min - matches builder task max runtime

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.build_dlq.arn
    maxReceiveCount     = 3
  })
}
