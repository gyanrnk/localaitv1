#!/usr/bin/env bash
# ============================================================
# load-secrets.sh  (Phase 1)
# ------------------------------------------------------------
# Push secrets from a LOCAL, untracked .env into AWS SSM Parameter
# Store as SecureString parameters under /localaitv/stg/.
#
# SAFETY:
#   * Reads values ONLY from a local .env (default: ../../../.env).
#   * REFUSES to run if that .env is tracked by git (prevents leaking
#     committed secrets / catching a misconfigured repo).
#   * DRY-RUN by default. Nothing is written to AWS unless --apply.
#   * Never prints secret values; only parameter names are shown.
#   * Only the param names listed in ssm-params.list are processed.
#
# Usage:
#   ./load-secrets.sh                 # dry-run, default .env + ssm-params.list
#   ./load-secrets.sh --apply         # actually write to SSM
#   ./load-secrets.sh --env-file /path/to/.env
#   ./load-secrets.sh --region ap-south-1
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Repo root is three levels up: deploy/aws/secrets -> repo root.
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

ENV_FILE="${REPO_ROOT}/.env"
PARAMS_FILE="${SCRIPT_DIR}/ssm-params.list"
REGION="ap-south-1"
APPLY=0

# ---------- arg parsing ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)      APPLY=1; shift ;;
    --env-file)   ENV_FILE="$2"; shift 2 ;;
    --params)     PARAMS_FILE="$2"; shift 2 ;;
    --region)     REGION="$2"; shift 2 ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

err()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "[load-secrets] $*"; }

# ---------- preconditions ----------
[[ -f "${ENV_FILE}" ]]    || err ".env file not found: ${ENV_FILE}"
[[ -f "${PARAMS_FILE}" ]] || err "params file not found: ${PARAMS_FILE}"
command -v aws >/dev/null 2>&1 || err "aws CLI not found on PATH."

# ---------- safety: refuse if .env is tracked by git ----------
if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git -C "${REPO_ROOT}" ls-files --error-unmatch "${ENV_FILE}" >/dev/null 2>&1; then
    err "REFUSING TO RUN: ${ENV_FILE} is TRACKED by git. Secrets must come from an untracked .env. Remove it from version control first (git rm --cached \"${ENV_FILE}\")."
  fi
  info "Safety check OK: .env is not tracked by git."
else
  info "Not a git work tree; skipping tracked-file check."
fi

if [[ "${APPLY}" -eq 1 ]]; then
  info "MODE: APPLY — parameters WILL be written to SSM (${REGION})."
else
  info "MODE: DRY-RUN — no changes will be made. Re-run with --apply to write."
fi
info "Env file : ${ENV_FILE}"
info "Params   : ${PARAMS_FILE}"
echo

# ---------- read a single key from .env (value never printed) ----------
get_env_value() {
  local key="$1"
  # Last matching assignment wins; strip optional surrounding quotes.
  local line
  line="$(grep -E "^[[:space:]]*${key}=" "${ENV_FILE}" | tail -n 1 || true)"
  [[ -n "${line}" ]] || return 1
  local val="${line#*=}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  printf '%s' "${val}"
}

written=0
skipped=0
missing=0

while IFS= read -r raw || [[ -n "${raw}" ]]; do
  # Skip comments and blank lines.
  param="$(printf '%s' "${raw}" | sed -e 's/#.*$//' -e 's/[[:space:]]//g')"
  [[ -n "${param}" ]] || continue

  # Derive the env-var key from the trailing path segment.
  key="${param##*/}"

  if ! value="$(get_env_value "${key}")"; then
    info "MISSING in .env, skipping: ${key}  (param ${param})"
    missing=$((missing + 1))
    continue
  fi

  if [[ -z "${value}" ]]; then
    info "EMPTY value in .env, skipping: ${key}  (param ${param})"
    skipped=$((skipped + 1))
    continue
  fi

  if [[ "${APPLY}" -eq 1 ]]; then
    aws ssm put-parameter \
      --region "${REGION}" \
      --name "${param}" \
      --type SecureString \
      --value "${value}" \
      --overwrite \
      --no-cli-pager >/dev/null
    info "WROTE SecureString: ${param}"
  else
    info "WOULD WRITE SecureString: ${param}"
  fi
  written=$((written + 1))
done < "${PARAMS_FILE}"

echo
info "Summary: ${written} param(s) $([[ ${APPLY} -eq 1 ]] && echo written || echo would-write), ${missing} missing, ${skipped} empty."
[[ "${APPLY}" -eq 1 ]] || info "Dry-run complete. No changes made."
