# Secrets — SSM Parameter Store (Phase 1)

Loads application secrets into **AWS SSM Parameter Store** as
`SecureString` parameters under the path prefix **`/localaitv/stg/`**.

No secret values live in this repo. Values are read at load time from a
**local, untracked `.env`** and pushed to SSM. At runtime the ECS task
definition injects them via `secrets` / `valueFrom` — the existing code
keeps using `os.getenv()` with no changes.

> Note: the param list is `ssm-params.list` (NOT `.txt`) because the repo
> `.gitignore` ignores `*.txt`, which would silently prevent the list from
> being committed.

## Files

| File              | Purpose                                                            |
| ----------------- | ----------------------------------------------------------------- |
| `ssm-params.list` | Parameter **paths only** (no values). Derived from `.env.example`. |
| `load-secrets.sh` | Loader: reads local `.env`, writes SecureString params.           |
| `README.md`       | This file.                                                        |

## Safety guarantees

- **No values committed.** `ssm-params.list` lists paths only; values come
  solely from a local `.env` (which is `.gitignore`d).
- **Refuses tracked `.env`.** The loader aborts if the `.env` it would
  read is tracked by git, so a misconfigured repo can't leak secrets.
- **Dry-run by default.** Nothing is written to AWS unless you pass
  `--apply`. The dry run prints which params *would* be written.
- **Never prints values.** Only parameter names appear in output.
- **Scoped.** Only the params listed in `ssm-params.list` are processed.

## Usage

```bash
# from deploy/aws/secrets/
chmod +x load-secrets.sh

# 1) Dry run — shows exactly what would be written (no AWS changes):
./load-secrets.sh

# 2) Apply — writes SecureString params to /localaitv/stg/ in ap-south-1:
./load-secrets.sh --apply

# Options:
./load-secrets.sh --env-file /custom/path/.env
./load-secrets.sh --region ap-south-1
```

By default the loader reads the repo-root `.env` (`../../../.env` relative
to this directory). Create it locally from `.env.example` and fill in real
values — never commit it.

## Which params are stored

Only secrets and credential-bearing URLs are stored as `SecureString`
(see `ssm-params.list`): the API keys, YouTube stream/data keys, AWS
fallback keys, and `DATABASE_URL`. Low-sensitivity configuration (ports,
model names, feature flags, region names) is intentionally **not** stored
here — it belongs in the task definition / image defaults.

> AWS credentials (`AWS_ACCESS_KEY_ID*`, `AWS_SECRET_ACCESS_KEY*`) are
> listed for parity with the current `.env` deployment, but prefer **IAM
> task roles** over static keys once tasks run on ECS.

## Prerequisites

- AWS CLI v2 configured for account `689186650531`, region `ap-south-1`,
  with permission to `ssm:PutParameter` under `/localaitv/stg/*`.
- A local `.env` populated from `.env.example`.
