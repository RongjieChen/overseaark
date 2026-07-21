#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

VLLM_WHEEL_NAME="vllm-${OVERSEAARK_VLLM_VERSION}+cu129-cp38-abi3-manylinux_2_28_aarch64.whl"
VLLM_WHEEL_CACHE="$OVERSEAARK_DATA_DIR/downloads/$VLLM_WHEEL_NAME"

vllm_install_ready() {
  [[ -x "$OVERSEAARK_VLLM_PYTHON" && -x "$OVERSEAARK_VLLM_BIN" ]] || return 1
  "$OVERSEAARK_VLLM_PYTHON" - "$OVERSEAARK_VLLM_VERSION" <<'PY' >/dev/null 2>&1
import sys
import torch
import vllm

expected = sys.argv[1]
version = vllm.__version__.split("+")[0]
raise SystemExit(
    0
    if version == expected and torch.cuda.is_available() and torch.version.cuda
    else 1
)
PY
}

download_vllm_wheel() {
  mkdir -p "$(dirname "$VLLM_WHEEL_CACHE")"
  if [[ -f "$VLLM_WHEEL_CACHE" ]] && \
      printf '%s  %s\n' "$OVERSEAARK_VLLM_WHEEL_SHA256" "$VLLM_WHEEL_CACHE" | sha256sum -c - >/dev/null 2>&1; then
    log "using verified cached vLLM wheel $VLLM_WHEEL_CACHE"
    return 0
  fi

  if [[ -f "$VLLM_WHEEL_CACHE" ]]; then
    warn "discarding invalid cached vLLM wheel $VLLM_WHEEL_CACHE"
    rm -f "$VLLM_WHEEL_CACHE"
  fi

  local partial="${VLLM_WHEEL_CACHE}.overseaark-download"
  local urls=("$OVERSEAARK_VLLM_WHEEL_URL")
  if [[ -n "$OVERSEAARK_GITHUB_ASSET_PREFIX" && "$OVERSEAARK_VLLM_WHEEL_URL" == https://github.com/* ]]; then
    urls+=("${OVERSEAARK_GITHUB_ASSET_PREFIX%/}/${OVERSEAARK_VLLM_WHEEL_URL}")
  fi

  local url downloaded=0
  for url in "${urls[@]}"; do
    log "downloading pinned native vLLM wheel"
    if curl --fail --location --continue-at - \
        --retry 20 --retry-all-errors --retry-delay 3 \
        --connect-timeout 20 --speed-time 120 --speed-limit 1024 \
        --output "$partial" "$url"; then
      downloaded=1
      break
    fi
    warn "vLLM wheel download failed from $url"
  done
  (( downloaded == 1 )) || die "unable to download pinned native vLLM wheel"
  printf '%s  %s\n' "$OVERSEAARK_VLLM_WHEEL_SHA256" "$partial" | sha256sum -c - >/dev/null || \
    die "downloaded vLLM wheel failed SHA256 verification"
  mv "$partial" "$VLLM_WHEEL_CACHE"
}

install_vllm() {
  if vllm_install_ready; then
    log "native vLLM $OVERSEAARK_VLLM_VERSION with CUDA is already installed"
    return 0
  fi
  [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "aarch64" ]] || \
    die "native vLLM bootstrap supports the target Linux aarch64 DGX Spark only"
  have nvidia-smi || die "NVIDIA driver is required for native vLLM"
  have python3 || die "Python 3.10-3.13 is required for native vLLM"
  python3 - <<'PY' || die "native vLLM requires Python 3.10-3.13"
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)
PY

  download_vllm_wheel
  if [[ ! -x "$OVERSEAARK_VLLM_PYTHON" ]]; then
    log "creating isolated native vLLM environment"
    python3 -m venv "$(dirname "$(dirname "$OVERSEAARK_VLLM_PYTHON")")"
  fi
  local pip="${OVERSEAARK_VLLM_PYTHON%/python}/pip"
  "$pip" install --index-url "$OVERSEAARK_PYPI_INDEX" --upgrade pip wheel setuptools
  "$pip" install \
    --index-url "$OVERSEAARK_PYPI_INDEX" \
    --extra-index-url https://download.pytorch.org/whl/cu129 \
    "$VLLM_WHEEL_CACHE"
  vllm_install_ready || die "native vLLM installed but CUDA import verification failed"
  "$OVERSEAARK_VLLM_PYTHON" - <<'PY'
import torch
import vllm
print(f"[overseaark] native vLLM {vllm.__version__}; torch {torch.__version__}; CUDA {torch.version.cuda}")
PY
}

vllm_health() {
  local pid
  pid="$(read_pid llm || true)"
  pid_alive "$pid" || return 1
  if have curl; then
    curl -fsS --max-time 3 "http://127.0.0.1:${OVERSEAARK_VLLM_PORT}/health" >/dev/null 2>&1
  else
    "$OVERSEAARK_VLLM_PYTHON" - "$OVERSEAARK_VLLM_PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=3).read()
PY
  fi
}

vllm_command() {
  local speculative='{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
  printf 'exec env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 %q serve %q' \
    "$OVERSEAARK_VLLM_BIN" "$OVERSEAARK_VLLM_MODEL_DIR"
  printf ' --served-model-name %q --host 127.0.0.1 --port %q' \
    "$OVERSEAARK_VLLM_SERVED_MODEL" "$OVERSEAARK_VLLM_PORT"
  printf ' --tensor-parallel-size 1 --trust-remote-code --quantization modelopt'
  printf ' --kv-cache-dtype fp8 --attention-backend flashinfer --moe-backend marlin'
  printf ' --gpu-memory-utilization %q --max-model-len %q --max-num-seqs %q' \
    "$OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION" "$OVERSEAARK_VLLM_MAX_MODEL_LEN" "$OVERSEAARK_VLLM_MAX_NUM_SEQS"
  printf ' --max-num-batched-tokens 8192 --enable-chunked-prefill --async-scheduling'
  printf ' --enable-prefix-caching --speculative-config %q' "$speculative"
  printf ' --load-format fastsafetensors --reasoning-parser qwen3'
  printf ' --tool-call-parser qwen3_xml --enable-auto-tool-choice\n'
}

wait_for_vllm() {
  local deadline=$((SECONDS + OVERSEAARK_VLLM_STARTUP_TIMEOUT))
  local last_notice=-1 pid
  while (( SECONDS < deadline )); do
    if vllm_health; then
      log "native vLLM health check passed"
      return 0
    fi
    pid="$(read_pid llm || true)"
    if [[ -n "$pid" ]] && ! pid_alive "$pid"; then
      warn "native vLLM exited during startup"
      tail -n 160 "$OVERSEAARK_LOG_DIR/llm.log" >&2 2>/dev/null || true
      return 1
    fi
    if (( SECONDS / 15 != last_notice )); then
      last_notice=$((SECONDS / 15))
      log "waiting for native vLLM model load (${SECONDS}s elapsed)"
    fi
    sleep 2
  done
  warn "native vLLM did not become healthy within ${OVERSEAARK_VLLM_STARTUP_TIMEOUT}s"
  tail -n 160 "$OVERSEAARK_LOG_DIR/llm.log" >&2 2>/dev/null || true
  return 1
}

start_vllm() {
  [[ -f "$OVERSEAARK_VLLM_MODEL_DIR/config.json" ]] || \
    die "Qwen3.6 model is missing at $OVERSEAARK_VLLM_MODEL_DIR; run ./overseaark models sync"
  vllm_install_ready || die "native vLLM is missing; run ./overseaark bootstrap"
  if vllm_health; then
    log "native vLLM already healthy"
    return 0
  fi

  local stale
  stale="$(read_pid llm || true)"
  if pid_alive "$stale"; then
    stop_one llm
  else
    remove_pid llm
  fi
  local command
  command="$(vllm_command)"
  start_one llm "$command" "$REPO_DIR"
  wait_for_vllm
}

stop_vllm() {
  stop_one llm
}

status_vllm() {
  local pid
  pid="$(read_pid llm || true)"
  if vllm_health; then
    printf '%-10s healthy pid=%s engine=vllm-%s bind=127.0.0.1:%s\n' \
      "llm" "$pid" "$OVERSEAARK_VLLM_VERSION" "$OVERSEAARK_VLLM_PORT"
  elif pid_alive "$pid"; then
    printf '%-10s loading pid=%s engine=vllm-%s\n' "llm" "$pid" "$OVERSEAARK_VLLM_VERSION"
  else
    printf '%-10s stopped engine=vllm-%s\n' "llm" "$OVERSEAARK_VLLM_VERSION"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-status}" in
    install) install_vllm ;;
    health) vllm_health ;;
    status) status_vllm ;;
    *) die "vllm command must be install, health, or status" 64 ;;
  esac
fi
