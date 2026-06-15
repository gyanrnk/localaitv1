# ============================================================
# ECR repository: laitv-stg-builder (Phase 1)
# ============================================================
# - Scan-on-push enabled.
# - Lifecycle policy expires UNTAGGED images after 14 days (configurable).
# - Tag mutability left MUTABLE so `latest` can be re-pointed by CI.
# ============================================================

resource "aws_ecr_repository" "builder" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "builder" {
  repository = aws_ecr_repository.builder.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.untagged_image_expiry_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_image_expiry_days
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
