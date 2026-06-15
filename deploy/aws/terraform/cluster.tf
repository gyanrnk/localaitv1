# ============================================================
# Phase 2 - ECS cluster (ECS-on-EC2, GPU) + capacity provider link
# ============================================================
# terraform apply is MANUAL and GATED.
#
# This is ECS-on-EC2 (GPU), NOT Fargate: Fargate has no GPU support, so
# the builder runs on g4dn.xlarge EC2 instances managed by the ASG +
# capacity provider defined in asg.tf.
#
# The capacity-provider association is declared here (separately from the
# capacity provider resource in asg.tf) and pins the default strategy to
# the GPU capacity provider with weight = 1 so the singleton builder
# service always lands on a GPU instance.
# ============================================================

resource "aws_ecs_cluster" "builders" {
  name = "laitv-${var.env}-builders"

  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }
}

# Associate the EC2 GPU capacity provider (defined in asg.tf) with the
# cluster and make it the default placement target.
resource "aws_ecs_cluster_capacity_providers" "builders" {
  cluster_name       = aws_ecs_cluster.builders.name
  capacity_providers = [aws_ecs_capacity_provider.builder.name]

  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.builder.name
    weight            = 1
    base              = 0
  }
}
