# ============================================================
# Phase 2 - Launch template + ASG + ECS capacity provider (GPU)
# ============================================================
# terraform apply is MANUAL and GATED.
#
# Capacity for the ECS-on-EC2 GPU builder cluster (cluster.tf):
#   - Launch template boots an ECS GPU-optimized AMI, joins the cluster,
#     and enables GPU support for the ECS agent.
#   - ASG: min 0 / desired 0 / max var.asg_max (default 2). Idle cost is
#     near-zero; a g4dn.xlarge launches only when the ECS managed-scaling
#     capacity provider needs capacity for a queued build job.
#   - max_size is bounded by the current On-Demand G/VT vCPU quota
#     (audit (b): 8 vCPU, quota L-DB2E81BA). g4dn.xlarge = 4 vCPU, so
#     floor(8 / 4) = 2 concurrent builders. Raise the quota AND
#     var.asg_max together for more parallelism.
#
# Worker is pull-based from SQS, so the security group has NO inbound
# rules - egress only (ECR pull, SQS, S3, CloudWatch, SSM endpoints).
# ============================================================

# --- Security group: egress-all, no inbound ---
resource "aws_security_group" "builder" {
  name        = "laitv-${var.env}-builder"
  description = "GPU builder instances - egress only (pull-based SQS worker, no inbound)."
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "Allow all outbound (ECR/SQS/S3/CloudWatch/SSM)."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "laitv-${var.env}-builder"
  }
}

# --- Launch template for the GPU container instances ---
resource "aws_launch_template" "builder" {
  name_prefix = "laitv-${var.env}-builder-"
  # local.ecs_gpu_ami_id = coalesce(var.ecs_gpu_ami_id, try(SSM value, "")).
  # In ap-south-1 the SSM GPU param does not resolve (audit (c)), so the
  # operator MUST set var.ecs_gpu_ami_id. An empty image_id fails apply.
  image_id      = local.ecs_gpu_ami_id
  instance_type = var.builder_instance_type

  iam_instance_profile {
    arn = aws_iam_instance_profile.ecs_instance.arn
  }

  vpc_security_group_ids = [aws_security_group.builder.id]

  # Larger root EBS for the GPU image layers + video scratch space.
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.builder_root_volume_gb
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  # ECS agent bootstrap: join the cluster and enable GPU support.
  user_data = base64encode(<<-EOT
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.builders.name}" >> /etc/ecs/ecs.config
    echo "ECS_ENABLE_GPU_SUPPORT=true" >> /etc/ecs/ecs.config
  EOT
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "laitv-${var.env}-builder"
    }
  }
}

# --- Auto Scaling Group (capacity for the capacity provider) ---
resource "aws_autoscaling_group" "builder" {
  name             = "laitv-${var.env}-builder"
  min_size         = 0
  desired_capacity = 0
  # max bounded by the current G/VT On-Demand quota (8 vCPU, L-DB2E81BA);
  # raise quota + var.asg_max for more parallelism.
  max_size            = var.asg_max
  vpc_zone_identifier = data.aws_subnets.default.ids

  launch_template {
    id      = aws_launch_template.builder.id
    version = "$Latest"
  }

  # Required for ECS managed termination protection.
  protect_from_scale_in = true

  # Marker tag so ECS recognizes the ASG as managed capacity.
  tag {
    key                 = "AmazonECSManaged"
    value               = ""
    propagate_at_launch = true
  }

  lifecycle {
    # ECS managed scaling owns desired_capacity at runtime.
    ignore_changes = [desired_capacity]
  }
}

# --- ECS capacity provider wrapping the ASG ---
resource "aws_ecs_capacity_provider" "builder" {
  name = "laitv-${var.env}-builder"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.builder.arn
    managed_termination_protection = "ENABLED"

    managed_scaling {
      status                    = "ENABLED"
      target_capacity           = 100
      minimum_scaling_step_size = 1
      maximum_scaling_step_size = 1
    }
  }
}
