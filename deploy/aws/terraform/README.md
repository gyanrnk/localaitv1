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

---

# Phase 2 — GPU builder (ECS-on-EC2 + SQS)

Phase 2 is **strictly additive** on top of Phase 1. It adds an
**ECS-on-EC2 GPU** cluster (Fargate has no GPU) whose builder task runs on
**g4dn.xlarge** instances, fed by an **SQS FIFO** build queue. The ASG and
ECS service idle at **0** and scale up only when a job is queued, so idle
cost is near-zero.

Networking reuses the **default VPC** (`vpc-0213982ec1cde401a`) and its
three `ap-south-1a/b/c` subnets via data sources — **no new VPC, NAT, or
subnets** are created. Phase 2 references (does not redeclare)
`data.aws_caller_identity.current` from `oidc.tf` and
`aws_ecr_repository.builder` from `ecr.tf`.

## ⚠️ Apply is MANUAL and GATED (Phase 2 too)

The backend is still **local** and there is **no automation**. Nothing is
created in AWS until an operator deliberately runs `terraform apply` after
reviewing the plan. Every Phase 2 file carries this reminder in its header.

## ⚠️ CRITICAL ap-south-1 caveats

**(a) ECS GPU AMI SSM params return `ParameterNotFound` in ap-south-1.**
Both `/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id`
and the AL2 equivalent are absent in this region (audit (c)). The
`aws_ssm_parameter.ecs_gpu_ami` data source is therefore **gated** (`count`)
and you **MUST** set `ecs_gpu_ami_id` explicitly:

```bash
# Find the latest ECS GPU-optimized AL2023 AMI id in ap-south-1:
aws ec2 describe-images \
  --region ap-south-1 \
  --owners amazon \
  --filters "Name=name,Values=al2023-ami-ecs-gpu-hvm-*-x86_64" \
            "Name=state,Values=available" \
  --query 'reverse(sort_by(Images,&CreationDate))[:1].[ImageId,Name]' \
  --output text

# Then pass it at apply time:
terraform apply -var="ecs_gpu_ami_id=ami-xxxxxxxxxxxxxxxxx"
```

`local.ecs_gpu_ami_id = coalesce(var.ecs_gpu_ami_id, try(SSM value, ""))`.
If both are empty the launch template gets an empty `image_id` and apply
fails — which is the intended guardrail.

**(b) On-Demand G/VT quota is 8 vCPU (quota `L-DB2E81BA`).** g4dn.xlarge =
4 vCPU, so `asg_max` is capped at **2** concurrent builders
(`floor(8 / 4) = 2`). To run more, request a quota increase for
`L-DB2E81BA` **and** raise `asg_max` together.

## The container command is a Phase-3 placeholder

The builder task command is `["python", "worker.py"]`, where **`worker.py`
is the Phase-3 SQS consumer that has not yet been written**. The ECS
service `desired_count` is `0`, so nothing runs. **No application files are
modified by Phase 2** — none of the `*.py`, `Dockerfile`, `Dockerfile.gpu`,
`docker-compose*.yml`, or `.github/workflows/*` files are touched. The
command is supplied only at the task-definition layer, exactly as
`Dockerfile.gpu` anticipates.

## New files (Phase 2)

| File                 | Purpose                                                                 |
| -------------------- | ----------------------------------------------------------------------- |
| `data.tf`            | Default VPC + subnets data sources; gated ECS GPU AMI SSM lookup.       |
| `sqs.tf`             | FIFO build queue + FIFO dead-letter queue (redrive maxReceiveCount 3).  |
| `cluster.tf`         | ECS cluster + capacity-provider association (default strategy weight 1).|
| `iam.tf`             | Instance role/profile, task-exec role, task role — all least-privilege. |
| `asg.tf`             | Launch template, security group (egress-only), ASG, capacity provider.  |
| `builder_service.tf` | GPU task definition (GPU=1) + ECS service (desired 0, capacity provider).|
| `autoscaling.tf`     | App Auto Scaling 0→2 on SQS `ApproximateNumberOfMessagesVisible`.       |
| `logs.tf`            | CloudWatch log group `/ecs/laitv-stg-builder`.                          |
| `outputs.tf`         | Cluster, queue, ASG, capacity provider, service, task def, log outputs. |

`variables.tf` is **extended** (Phase 2 variables appended) and this
`README.md` is **extended** with this section — no Phase 1 content removed.

## Variables (Phase 2)

| Variable                    | Default                                                                       | Notes                                                              |
| --------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `ecs_gpu_ami_ssm_param`     | `/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id`   | Does NOT resolve in ap-south-1; data source is gated.             |
| `ecs_gpu_ami_id`            | `""`                                                                          | **REQUIRED override in ap-south-1** (caveat (a)).                 |
| `builder_instance_type`     | `g4dn.xlarge`                                                                 | One builder task per host.                                        |
| `asg_max`                   | `2`                                                                           | `floor(8 vCPU / 4)` per G/VT quota `L-DB2E81BA` (caveat (b)).     |
| `builder_root_volume_gb`    | `100`                                                                         | GPU image layers + video scratch.                                |
| `builder_image_tag`         | `latest`                                                                      | Image tag in `laitv-stg-builder`.                                |
| `builder_command`           | `["python","worker.py"]`                                                      | **Phase-3 placeholder** (worker.py not yet written).             |
| `builder_secret_keys`       | `["OPENAI_API_KEY","DATABASE_URL","S3_BUCKET_NAME"]`                          | Resolved under `/localaitv/<env>/`.                              |
| `s3_bucket_arns`            | `[]`                                                                          | App buckets for the task role; empty disables the S3 statements.  |
| `log_retention_days`        | `30`                                                                          | Builder log group retention.                                      |
| `enable_container_insights` | `false`                                                                       | Off by default to save cost.                                     |

## Cost posture

ASG `min 0 / desired 0` and appautoscaling `min 0`. A g4dn.xlarge launches
only when `ApproximateNumberOfMessagesVisible >= 1` and drains back to `0`
when the queue empties (`autoscaling.tf` step policies + the ECS
managed-scaling capacity provider). Container Insights is off by default.

## Teardown (Phase 2)

`terraform destroy` removes the Phase 2 resources alongside Phase 1. The
default VPC/subnets are referenced via data sources and are **not**
destroyed. The shared OIDC provider remains untouched under the default
config.
