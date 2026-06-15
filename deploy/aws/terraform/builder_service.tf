# ============================================================
# Phase 2 - Builder task definition + ECS service (GPU singleton)
# ============================================================
# terraform apply is MANUAL and GATED.
#
# IMPORTANT - PHASE 3 PLACEHOLDER COMMAND:
#   The container `command` is ["python", "worker.py"], where worker.py
#   is the Phase 3 SQS consumer that has NOT YET been written. Until
#   Phase 3 lands that file in the image, this task is NOT RUNNABLE - the
#   service desired_count is 0 so nothing is launched. This file does NOT
#   (and must not) change any application .py / Dockerfile / compose / CI
#   files; the command is supplied here at the task-definition layer
#   exactly as Dockerfile.gpu anticipates.
#
# ECS-on-EC2 GPU: requires_compatibilities = ["EC2"], bridge networking
# (one builder task per g4dn.xlarge), GPU=1 resource requirement.
# ============================================================

resource "aws_ecs_task_definition" "builder" {
  family                   = "laitv-${var.env}-builder"
  requires_compatibilities = ["EC2"]
  network_mode             = "bridge"
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.task.arn

  # Sized for one builder task per g4dn.xlarge (4 vCPU / 16 GiB), leaving
  # headroom for the ECS agent + OS. GPU=1 is the whole card on the host.
  cpu    = "3072"
  memory = "14336"

  container_definitions = jsonencode([
    {
      name      = "builder"
      image     = "${aws_ecr_repository.builder.repository_url}:${var.builder_image_tag}"
      essential = true

      resourceRequirements = [
        {
          type  = "GPU"
          value = "1"
        }
      ]

      # Phase 3 SQS consumer entrypoint. worker.py is NOT yet written;
      # this is a placeholder so the task definition is complete. Do not
      # treat the task as runnable until Phase 3 ships worker.py.
      command = var.builder_command

      environment = [
        { name = "SQS_BUILD_QUEUE_URL", value = aws_sqs_queue.build.url },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "BUILD_BACKEND", value = "sqs" },
      ]

      # Secrets resolved by the task-exec role from SSM at container start.
      # Path prefix is /localaitv/${env}/<key> (see iam.tf).
      secrets = [
        for k in var.builder_secret_keys : {
          name      = k
          valueFrom = "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter/localaitv/${var.env}/${k}"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.builder.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "builder"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "builder" {
  name            = "laitv-${var.env}-builder"
  cluster         = aws_ecs_cluster.builders.id
  task_definition = aws_ecs_task_definition.builder.arn

  # Singleton, idle by default. Application Auto Scaling (autoscaling.tf)
  # owns desired_count at runtime, driven by SQS queue depth.
  desired_count = 0

  # launch_type omitted on purpose - placement is via the GPU capacity
  # provider strategy below (weight = 1).
  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.builder.name
    weight            = 1
    base              = 0
  }

  # Singleton scaling: never run two copies of the same task at once.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  lifecycle {
    # app-autoscaling owns desired_count; don't fight it on plan.
    ignore_changes = [desired_count]
  }

  # Ensure the cluster<->capacity-provider association exists first.
  depends_on = [aws_ecs_cluster_capacity_providers.builders]
}
