# ============================================================
# Phase 2 - IAM (least-privilege) for ECS-on-EC2 GPU builder
# ============================================================
# terraform apply is MANUAL and GATED.
#
# Four constructs, all least-privilege, matching the oidc.tf style of
# building policies with aws_iam_policy_document:
#   1. ECS instance role + instance profile  -> asg.tf launch template
#   2. Task execution role                   -> pulls image, reads SSM
#                                               secrets, writes logs
#   3. Task role                             -> SQS consume + S3 + SSM
#                                               at container runtime
#
# Reuses data.aws_caller_identity.current (declared in oidc.tf).
# Uses the SSM secret PATH prefix /localaitv/${env}/* (per task spec),
# which intentionally differs from the resource NAME prefix laitv-${env}-*.
# ============================================================

locals {
  account_id = data.aws_caller_identity.current.account_id

  # SSM Parameter Store path that holds the builder's runtime secrets.
  # NOTE: path prefix is /localaitv/<env>/* (NOT laitv-<env>-*).
  ssm_secret_arn_prefix = "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter/localaitv/${var.env}/*"
}

# ------------------------------------------------------------
# (1) ECS container-instance role + instance profile
# ------------------------------------------------------------
data "aws_iam_policy_document" "ecs_instance_trust" {
  statement {
    sid     = "EC2AssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_instance" {
  name               = "laitv-${var.env}-ecs-instance"
  description        = "Role for ECS GPU container instances (EC2) - register with the cluster + SSM management."
  assume_role_policy = data.aws_iam_policy_document.ecs_instance_trust.json
}

# Lets the EC2 instance register with ECS, pull from ECR, etc.
resource "aws_iam_role_policy_attachment" "ecs_instance_ecs" {
  role       = aws_iam_role.ecs_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

# SSM Session Manager / Fleet Manager access for ops (no inbound SSH).
resource "aws_iam_role_policy_attachment" "ecs_instance_ssm" {
  role       = aws_iam_role.ecs_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ecs_instance" {
  name = "laitv-${var.env}-ecs-instance"
  role = aws_iam_role.ecs_instance.name
}

# ------------------------------------------------------------
# (2) Task EXECUTION role (used by the ECS agent, not the app)
# ------------------------------------------------------------
data "aws_iam_policy_document" "task_exec_trust" {
  statement {
    sid     = "ECSTasksAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_exec" {
  name               = "laitv-${var.env}-builder-task-exec"
  description        = "ECS task execution role: pull image, resolve SSM secrets, ship logs."
  assume_role_policy = data.aws_iam_policy_document.task_exec_trust.json
}

# Baseline: ECR pull + CloudWatch Logs as needed by the agent.
resource "aws_iam_role_policy_attachment" "task_exec_managed" {
  role       = aws_iam_role.task_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Inline least-priv: resolve `secrets` valueFrom at container start,
# pull the builder image, and create/write the task's log stream.
data "aws_iam_policy_document" "task_exec_inline" {
  # SSM secrets used by container `secrets` valueFrom.
  statement {
    sid    = "ReadBuilderSecrets"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = [local.ssm_secret_arn_prefix]
  }

  # Decrypt SecureString params encrypted with the SSM default KMS key.
  statement {
    sid       = "DecryptSSMDefaultKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${local.account_id}:alias/aws/ssm"]
  }

  # ECR auth token is a wildcard-only action (no resource scoping).
  statement {
    sid       = "ECRGetAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Pull the builder image (scoped to the single builder repo, ecr.tf).
  statement {
    sid    = "ECRPullBuilderImage"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = [aws_ecr_repository.builder.arn]
  }

  # Write the builder task's logs (scoped to the Phase 2 log group).
  statement {
    sid    = "WriteBuilderLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.builder.arn}:*"]
  }
}

resource "aws_iam_role_policy" "task_exec_inline" {
  name   = "laitv-${var.env}-builder-task-exec-inline"
  role   = aws_iam_role.task_exec.id
  policy = data.aws_iam_policy_document.task_exec_inline.json
}

# ------------------------------------------------------------
# (3) Task ROLE (the app/worker's own runtime permissions)
# ------------------------------------------------------------
resource "aws_iam_role" "task" {
  name               = "laitv-${var.env}-builder-task"
  description        = "Builder task runtime role: consume SQS, read/write app S3, read SSM secrets."
  assume_role_policy = data.aws_iam_policy_document.task_exec_trust.json
}

data "aws_iam_policy_document" "task_inline" {
  # Consume build jobs from the FIFO queue.
  statement {
    sid    = "ConsumeBuildQueue"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.build.arn]
  }

  # Allow explicit park-to-DLQ sends from the worker.
  statement {
    sid       = "SendToDLQ"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.build_dlq.arn]
  }

  # Read runtime secrets directly (in addition to container `secrets`).
  statement {
    sid    = "ReadRuntimeSecrets"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = [local.ssm_secret_arn_prefix]
  }

  # App S3 buckets - only emitted when var.s3_bucket_arns is non-empty.
  dynamic "statement" {
    for_each = length(var.s3_bucket_arns) > 0 ? [1] : []
    content {
      sid    = "AppS3ObjectAccess"
      effect = "Allow"
      actions = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
      ]
      resources = [for b in var.s3_bucket_arns : "${b}/*"]
    }
  }

  dynamic "statement" {
    for_each = length(var.s3_bucket_arns) > 0 ? [1] : []
    content {
      sid       = "AppS3ListBuckets"
      effect    = "Allow"
      actions   = ["s3:ListBucket"]
      resources = var.s3_bucket_arns
    }
  }
}

resource "aws_iam_role_policy" "task_inline" {
  name   = "laitv-${var.env}-builder-task-inline"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_inline.json
}
