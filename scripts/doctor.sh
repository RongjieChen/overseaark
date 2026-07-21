#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

ensure_dirs
failures=0

check() {
  local name="$1"
  shift
  if "$@"; then
    printf '[ok]   %s\n' "$name"
  else
    printf '[fail] %s\n' "$name"
    failures=$((failures + 1))
  fi
}

check_warn() {
  local name="$1"
  shift
  if "$@"; then
    printf '[ok]   %s\n' "$name"
  else
    printf '[warn] %s\n' "$name"
  fi
}

is_localhost_bind() {
  [[ "$OVERSEAARK_HOST" == "127.0.0.1" || "$OVERSEAARK_HOST" == "localhost" ]]
}

check "localhost-only backend bind ($OVERSEAARK_HOST)" is_localhost_bind
check "writable data dir" test -w "$OVERSEAARK_DATA_DIR"
check "writable pid dir" test -w "$OVERSEAARK_PID_DIR"
check "model manifest exists" test -f "$REPO_DIR/model-manifest.lock.json"
check_warn "python3 available" have python3
check_warn "npm available for frontend builds" have npm
check_warn "nvidia-smi available" have nvidia-smi

if have uname; then
  arch="$(uname -m)"
  case "$arch" in
    aarch64|arm64) printf '[ok]   architecture %s\n' "$arch" ;;
    *) printf '[warn] architecture %s (target is aarch64 DGX Spark)\n' "$arch" ;;
  esac
fi

if have nvidia-smi; then
  nvidia-smi >/dev/null || failures=$((failures + 1))
fi

if ! is_truthy "$OVERSEAARK_SKIP_MODELS" && ! is_truthy "$OVERSEAARK_MOCK_MODE"; then
  bash "$SCRIPT_DIR/models.sh" verify || failures=$((failures + 1))
else
  printf '[warn] model checks relaxed by skip/mock mode\n'
fi

if (( failures > 0 )); then
  die "doctor found $failures failure(s)"
fi

log "doctor passed"
