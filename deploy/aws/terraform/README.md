# Terraform — Phase 1 (ECR + GitHub OIDC)

Region: **ap-south-1** · Env: **stg** · Account: **689186650531**

This module creates the minimum AWS resources needed for CI to build and
push the GPU builder image:

- **ECR repository** `laitv-stg-builder` — scan-on-push, lifecycle policy
  that expires untagged images after 14 days.
- **IAM role** `laitv-stg-gha-ecr-push` — assumed via **GitHub OIDC** by
  `repo:gyanrnk/localaitv1:*` (audience `sts.amazonaws.com`), with a
  least-privilege ECR push policy scoped to the single builder repo.

It outputs the role ARN, which you then store as the GitHub secret
`AWS_OIDC_ROLE_ARN` used by `.github/workflows/aws-ecr.yml`.

## ⚠️ Apply is MANUAL and GATED

There is **no remote backend and no automation** that runs `apply`. Nothing
is created in AWS until an operator deliberately runs the commands below.
Phase 1 is additive-only — review every planned resource before applying.

## OIDC provider already exists — do NOT recreate it

The GitHub OIDC provider `token.actions.githubusercontent.com` was already
created in this account on 2026-02-06. This module **references** it by
default (`create_oidc_provider = false`) so it is not duplicated. Leave the
default unless you are bootstrapping a brand-new account.

## Usage

```bash
# from deploy/aws/terraform/
terraform init

# Review carefully — confirm only ECR + IAM role/policy are planned.
terraform plan

# Only after review, with explicit confirmation:
terraform apply

# Capture the role ARN and set it as a GitHub Actions secret:
terraform output -raw github_ecr_push_role_arn
# -> gh secret set AWS_OIDC_ROLE_ARN --body "<that arn>"
```

## Files

| File           | Purpose                                                      |
| -------------- | ----------------------------------------------------------- |
| `providers.tf` | AWS provider, ap-south-1, local backend, default tags.      |
| `variables.tf` | Region, env, repo/owner, expiry days, OIDC create toggle.   |
| `ecr.tf`       | ECR repo + lifecycle policy (expire untagged 14d).          |
| `oidc.tf`      | OIDC provider reference, IAM role + least-priv push policy. |

## Variables

| Variable                     | Default            | Notes                                  |
| ---------------------------- | ------------------ | -------------------------------------- |
| `aws_region`                 | `ap-south-1`       |                                        |
| `env`                        | `stg`              | Resource prefix `laitv-<env>-*`.       |
| `ecr_repository_name`        | `laitv-stg-builder`|                                        |
| `untagged_image_expiry_days` | `14`               | Lifecycle expiry for untagged images.  |
| `github_owner`               | `gyanrnk`          |                                        |
| `github_repo`                | `localaitv1`       |                                        |
| `create_oidc_provider`       | `false`            | Reuses existing provider by default.   |

## Teardown

`terraform destroy` removes only the resources in this module (ECR repo +
IAM role/policy). The shared OIDC provider is **not** destroyed because it
is referenced via a data source (not managed here) under the default config.
