# ============================================================
# GitHub OIDC provider + IAM role for CI ECR push (Phase 1)
# ============================================================
# The OIDC provider token.actions.githubusercontent.com already exists in
# account 689186650531 (created 2026-02-06). By default we REFERENCE the
# existing provider (data source) rather than creating a duplicate.
#
# The IAM role trusts the GitHub repo  repo:gyanrnk/localaitv1:*  with
# audience  sts.amazonaws.com  and grants ONLY the ECR permissions needed
# to push the builder image. The role ARN is consumed by the GitHub secret
# AWS_OIDC_ROLE_ARN used in .github/workflows/aws-ecr.yml.
# ============================================================

data "aws_caller_identity" "current" {}

locals {
  github_oidc_url      = "token.actions.githubusercontent.com"
  github_oidc_arn      = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.github_oidc_url}"
  github_subject_claim = "repo:${var.github_owner}/${var.github_repo}:*"
}

# --- Optionally create the provider (default: reuse existing) ---
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url             = "https://${local.github_oidc_url}"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- Reference the existing provider (default path) ---
data "aws_iam_openid_connect_provider" "github_existing" {
  count = var.create_oidc_provider ? 0 : 1
  arn   = local.github_oidc_arn
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github_existing[0].arn
}

# --- Trust policy: GitHub Actions from gyanrnk/localaitv1 only ---
data "aws_iam_policy_document" "github_trust" {
  statement {
    sid     = "GitHubOIDCAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "${local.github_oidc_url}:sub"
      values   = [local.github_subject_claim]
    }
  }
}

resource "aws_iam_role" "github_ecr_push" {
  name                 = "laitv-${var.env}-gha-ecr-push"
  description          = "GitHub Actions OIDC role for pushing the GPU builder image to ECR (least-priv)."
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

# --- Least-privilege ECR push policy ---
data "aws_iam_policy_document" "ecr_push" {
  # Auth token is a wildcard-only action (no resource scoping possible).
  statement {
    sid       = "ECRGetAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Push/pull layers + manifests, scoped to the single builder repo.
  statement {
    sid    = "ECRPushToBuilderRepo"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
    ]
    resources = [aws_ecr_repository.builder.arn]
  }
}

resource "aws_iam_role_policy" "ecr_push" {
  name   = "laitv-${var.env}-ecr-push"
  role   = aws_iam_role.github_ecr_push.id
  policy = data.aws_iam_policy_document.ecr_push.json
}

# ============================================================
# Outputs
# ============================================================
output "github_ecr_push_role_arn" {
  description = "IAM role ARN to set as the GitHub secret AWS_OIDC_ROLE_ARN."
  value       = aws_iam_role.github_ecr_push.arn
}

output "ecr_repository_url" {
  description = "ECR repository URL for the GPU builder image."
  value       = aws_ecr_repository.builder.repository_url
}
