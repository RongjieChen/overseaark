#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

modality="${1:-}"
case "$modality" in
  llm|image|audio|video) ;;
  *) die "usage: ./overseaark benchmark llm|image|audio|video" 64 ;;
esac

ensure_dirs
local_runtime_env

if ! is_truthy "$OVERSEAARK_MOCK_MODE"; then
  bash "$SCRIPT_DIR/models.sh" verify
  validate_offline_runtime
  py="$(python_bin)" || die "python3 is required"
  "$py" "$SCRIPT_DIR/run_benchmark.py" "$modality" "$OVERSEAARK_DATA_DIR/benchmarks"
  log "$modality benchmark complete"
  exit 0
fi

started=0
pid="$(read_pid backend || true)"
if ! pid_alive "$pid"; then
  if is_truthy "$OVERSEAARK_MOCK_MODE"; then
    bash "$SCRIPT_DIR/lifecycle.sh" start
    started=1
  else
    die "backend is not running; run ./overseaark start first"
  fi
fi

url="http://${OVERSEAARK_HOST}:${OVERSEAARK_BACKEND_PORT}"
if have curl; then
  if curl -fsS --max-time 2 "$url/health" >/dev/null; then
    log "$modality benchmark health probe passed at $url/health"
  elif curl -fsS --max-time 2 "$url" >/dev/null; then
    log "$modality benchmark root probe passed at $url"
  elif is_truthy "$OVERSEAARK_MOCK_MODE"; then
    warn "$modality benchmark using mock mode; HTTP endpoint did not expose /health"
  else
    die "$modality benchmark probe failed"
  fi
else
  warn "curl not available; benchmark limited to process/model checks"
fi

if (( started == 1 )); then
  bash "$SCRIPT_DIR/lifecycle.sh" stop
fi

log "$modality benchmark smoke complete"
