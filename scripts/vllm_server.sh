#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

vllm_install_ready() {
  [[ -x "$OVERSEAARK_VLLM_BIN" ]] || return 1
  [[ -x "$OVERSEAARK_VLLM_ENV_DIR/bin/ninja" ]] || return 1
  "$OVERSEAARK_VLLM_ENV_DIR/bin/python" - "$OVERSEAARK_VLLM_VERSION" <<'PY' >/dev/null 2>&1
import sys
import torch
import vllm

expected = sys.argv[1]
raise SystemExit(
    0
    if vllm.__version__.split("+")[0] == expected
    and torch.cuda.is_available()
    else 1
)
PY
}

install_vllm() {
  if vllm_install_ready; then
    log "pinned native vLLM $OVERSEAARK_VLLM_VERSION is already installed"
    return 0
  fi
  [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "aarch64" ]] || \
    die "native vLLM bootstrap supports the target Linux aarch64 DGX Spark only"
  have nvidia-smi || die "NVIDIA driver is required for native vLLM"
  have python3 || die "Python 3.12 is required for native vLLM"
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' || \
    die "native vLLM requires Python 3.12"

  local download_dir wheel_name wheel_path
  download_dir="$OVERSEAARK_DATA_DIR/downloads"
  wheel_name="vllm-${OVERSEAARK_VLLM_VERSION}+cu129-cp38-abi3-manylinux_2_28_aarch64.whl"
  wheel_path="$download_dir/$wheel_name"
  mkdir -p "$download_dir"
  if [[ ! -f "$wheel_path" ]] || \
      ! printf '%s  %s\n' "$OVERSEAARK_VLLM_WHEEL_SHA256" "$wheel_path" | sha256sum -c - >/dev/null 2>&1; then
    log "downloading pinned official vLLM ARM64 CUDA wheel"
    curl -fL --retry 5 --retry-delay 2 -C - -o "$wheel_path" "$OVERSEAARK_VLLM_WHEEL_URL" || {
      warn "resumable vLLM wheel download failed; retrying from byte zero"
      find "$wheel_path" -maxdepth 0 -type f -delete 2>/dev/null || true
      curl -fL --retry 5 --retry-delay 2 -o "$wheel_path" "$OVERSEAARK_VLLM_WHEEL_URL"
    }
  fi
  printf '%s  %s\n' "$OVERSEAARK_VLLM_WHEEL_SHA256" "$wheel_path" | sha256sum -c -

  if [[ ! -x "$OVERSEAARK_VLLM_ENV_DIR/bin/python" ]]; then
    python3 -m venv "$OVERSEAARK_VLLM_ENV_DIR"
  fi
  "$OVERSEAARK_VLLM_ENV_DIR/bin/pip" install \
    --index-url "$OVERSEAARK_PYPI_INDEX" \
    --upgrade pip wheel setuptools
  "$OVERSEAARK_VLLM_ENV_DIR/bin/pip" install \
    --index-url "$OVERSEAARK_PYPI_INDEX" \
    --upgrade "$wheel_path"
  vllm_install_ready || die "vLLM installation completed but CUDA runtime verification failed"
  "$OVERSEAARK_VLLM_BIN" --version
}

vllm_health() {
  local pid
  pid="$(read_pid llm || true)"
  pid_alive "$pid" || return 1
  if have curl; then
    curl -fsS --max-time 3 "http://127.0.0.1:${OVERSEAARK_VLLM_PORT}/health" >/dev/null 2>&1
  else
    local py
    py="$(python_bin)" || return 1
    "$py" - "$OVERSEAARK_VLLM_PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=3).read()
PY
  fi
}

ensure_vllm_api_key() {
  mkdir -p "$(dirname "$OVERSEAARK_VLLM_API_KEY_FILE")"
  if [[ ! -s "$OVERSEAARK_VLLM_API_KEY_FILE" ]]; then
    local py
    py="$(python_bin)" || die "python3 is required to create the local vLLM API key"
    (umask 077; "$py" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$OVERSEAARK_VLLM_API_KEY_FILE")
  fi
  chmod 600 "$OVERSEAARK_VLLM_API_KEY_FILE"
}

vllm_command() {
  local api_key runtime_path
  api_key="$(<"$OVERSEAARK_VLLM_API_KEY_FILE")"
  runtime_path="$OVERSEAARK_VLLM_ENV_DIR/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  # FlashInfer can otherwise launch one nvcc process per generated kernel. On
  # unified-memory systems that lets JIT compilation contend with the loaded
  # model and the Linux OOM killer can terminate individual compiler jobs.
  printf 'exec env PATH=%q CUDA_HOME=/usr/local/cuda TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas MAX_JOBS=1 CMAKE_BUILD_PARALLEL_LEVEL=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 DO_NOT_TRACK=1 VLLM_NO_USAGE_STATS=1 VLLM_API_KEY=%q %q serve %q' \
    "$runtime_path" "$api_key" "$OVERSEAARK_VLLM_BIN" "$OVERSEAARK_VLLM_MODEL_DIR"
  printf ' --served-model-name %q --host 127.0.0.1 --port %q' \
    "$OVERSEAARK_VLLM_SERVED_MODEL" "$OVERSEAARK_VLLM_PORT"
  printf ' --tensor-parallel-size 1 --trust-remote-code --kv-cache-dtype fp8'
  printf ' --attention-backend flashinfer --moe-backend marlin'
  printf ' --gpu-memory-utilization %q --max-model-len %q' \
    "$OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION" "$OVERSEAARK_VLLM_MAX_MODEL_LEN"
  printf ' --max-num-seqs %q --max-num-batched-tokens %q' \
    "$OVERSEAARK_VLLM_MAX_NUM_SEQS" "$OVERSEAARK_VLLM_MAX_NUM_BATCHED_TOKENS"
  printf ' --enable-chunked-prefill --async-scheduling --enable-prefix-caching'
  printf ' --speculative-config %q' '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
  printf ' --load-format fastsafetensors --reasoning-parser qwen3'
  printf ' --tool-call-parser qwen3_xml --enable-auto-tool-choice\n'
}

wait_for_vllm() {
  local deadline=$((SECONDS + OVERSEAARK_VLLM_STARTUP_TIMEOUT))
  local last_notice=-1 pid
  while (( SECONDS < deadline )); do
    if vllm_health; then
      log "vLLM health check passed"
      return 0
    fi
    pid="$(read_pid llm || true)"
    if [[ -n "$pid" ]] && ! pid_alive "$pid"; then
      warn "vLLM exited during startup"
      tail -n 200 "$OVERSEAARK_LOG_DIR/llm.log" >&2 2>/dev/null || true
      return 1
    fi
    if (( SECONDS / 15 != last_notice )); then
      last_notice=$((SECONDS / 15))
      log "waiting for vLLM model load (${SECONDS}s elapsed)"
    fi
    sleep 2
  done
  warn "vLLM did not become healthy within ${OVERSEAARK_VLLM_STARTUP_TIMEOUT}s"
  tail -n 200 "$OVERSEAARK_LOG_DIR/llm.log" >&2 2>/dev/null || true
  return 1
}

start_vllm() {
  [[ -f "$OVERSEAARK_VLLM_MODEL_DIR/config.json" ]] || \
    die "Qwen3.6 NVFP4 is missing at $OVERSEAARK_VLLM_MODEL_DIR; run ./overseaark models sync"
  [[ -f "$OVERSEAARK_VLLM_MODEL_DIR/model-00003-of-00003.safetensors" ]] || \
    die "Qwen3.6 NVFP4 third shard is missing; run ./overseaark models sync"
  vllm_install_ready || die "pinned native vLLM is missing; run ./overseaark bootstrap"
  ensure_vllm_api_key
  if vllm_health; then
    log "vLLM already healthy"
    return 0
  fi

  local stale command
  stale="$(read_pid llm || true)"
  if pid_alive "$stale"; then
    stop_one llm
  else
    remove_pid llm
  fi
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
    printf '%-10s healthy pid=%s engine=vllm@%s bind=127.0.0.1:%s\n' \
      "llm" "$pid" "$OVERSEAARK_VLLM_VERSION" "$OVERSEAARK_VLLM_PORT"
  elif pid_alive "$pid"; then
    printf '%-10s loading pid=%s engine=vllm@%s\n' "llm" "$pid" "$OVERSEAARK_VLLM_VERSION"
  else
    printf '%-10s stopped engine=vllm@%s\n' "llm" "$OVERSEAARK_VLLM_VERSION"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-status}" in
    install) install_vllm ;;
    health) vllm_health ;;
    status) status_vllm ;;
    *) die "vllm-server command must be install, health, or status" 64 ;;
  esac
fi
