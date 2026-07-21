#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

llama_install_ready() {
  [[ -x "$OVERSEAARK_LLAMA_SERVER" ]] || return 1
  [[ -d "$OVERSEAARK_LLAMA_CPP_DIR/.git" ]] || return 1
  [[ "$(git -C "$OVERSEAARK_LLAMA_CPP_DIR" rev-parse HEAD 2>/dev/null)" == "$OVERSEAARK_LLAMA_REVISION" ]] || return 1
  "$OVERSEAARK_LLAMA_SERVER" --version 2>&1 | grep -Eq '^version:' || return 1
}

install_llama_cpp() {
  if llama_install_ready; then
    log "pinned CUDA llama.cpp $OVERSEAARK_LLAMA_REVISION is already installed"
    return 0
  fi
  [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "aarch64" ]] || \
    die "CUDA llama.cpp bootstrap supports the target Linux aarch64 DGX Spark only"
  have nvidia-smi || die "NVIDIA driver is required for CUDA llama.cpp"
  have git || die "git is required to build llama.cpp"
  have cmake || die "cmake is required to build llama.cpp"
  have c++ || die "a C++ compiler is required to build llama.cpp"
  have nvcc || [[ -x /usr/local/cuda/bin/nvcc ]] || die "CUDA nvcc is required to build llama.cpp"

  local repository_url="https://github.com/ggml-org/llama.cpp.git"
  if [[ -n "$OVERSEAARK_GITHUB_GIT_PREFIX" ]]; then
    repository_url="${OVERSEAARK_GITHUB_GIT_PREFIX%/}/ggml-org/llama.cpp.git"
  fi
  mkdir -p "$(dirname "$OVERSEAARK_LLAMA_CPP_DIR")"
  if [[ ! -d "$OVERSEAARK_LLAMA_CPP_DIR/.git" ]]; then
    log "cloning llama.cpp"
    git clone --filter=blob:none --no-checkout "$repository_url" "$OVERSEAARK_LLAMA_CPP_DIR"
  fi
  if ! git -C "$OVERSEAARK_LLAMA_CPP_DIR" cat-file -e "${OVERSEAARK_LLAMA_REVISION}^{commit}"; then
    git -C "$OVERSEAARK_LLAMA_CPP_DIR" fetch --depth 1 "$repository_url" "$OVERSEAARK_LLAMA_REVISION"
  fi
  git -C "$OVERSEAARK_LLAMA_CPP_DIR" checkout --detach "$OVERSEAARK_LLAMA_REVISION"

  local cuda_compiler="${CUDACXX:-}"
  if [[ -z "$cuda_compiler" && -x /usr/local/cuda/bin/nvcc ]]; then
    cuda_compiler=/usr/local/cuda/bin/nvcc
  fi
  log "building pinned llama.cpp with CUDA"
  cmake -S "$OVERSEAARK_LLAMA_CPP_DIR" -B "$OVERSEAARK_LLAMA_BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CUDA_COMPILER="$cuda_compiler" \
    -DGGML_CUDA=ON \
    -DGGML_NATIVE=ON \
    -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF \
    -DLLAMA_BUILD_TOOLS=ON \
    -DLLAMA_BUILD_SERVER=ON
  cmake --build "$OVERSEAARK_LLAMA_BUILD_DIR" --target llama-server -j "${OVERSEAARK_BUILD_JOBS:-$(nproc)}"
  llama_install_ready || die "llama.cpp built but pinned CUDA server verification failed"
  "$OVERSEAARK_LLAMA_SERVER" --version
}

llama_health() {
  local pid
  pid="$(read_pid llm || true)"
  pid_alive "$pid" || return 1
  if have curl; then
    curl -fsS --max-time 3 "http://127.0.0.1:${OVERSEAARK_LLAMA_PORT}/health" >/dev/null 2>&1
  else
    local py
    py="$(python_bin)" || return 1
    "$py" - "$OVERSEAARK_LLAMA_PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=3).read()
PY
  fi
}

ensure_llama_api_key() {
  mkdir -p "$(dirname "$OVERSEAARK_LLAMA_API_KEY_FILE")"
  if [[ ! -s "$OVERSEAARK_LLAMA_API_KEY_FILE" ]]; then
    local py
    py="$(python_bin)" || die "python3 is required to create the local llama.cpp API key"
    (umask 077; "$py" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$OVERSEAARK_LLAMA_API_KEY_FILE")
  fi
  chmod 600 "$OVERSEAARK_LLAMA_API_KEY_FILE"
}

llama_command() {
  printf 'exec env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 DO_NOT_TRACK=1 %q' \
    "$OVERSEAARK_LLAMA_SERVER"
  printf ' --model %q --mmproj %q --alias %q' \
    "$OVERSEAARK_LLAMA_MODEL" "$OVERSEAARK_LLAMA_MMPROJ" "$OVERSEAARK_LLAMA_SERVED_MODEL"
  printf ' --api-key-file %q --cors-origins localhost --no-cors-credentials' \
    "$OVERSEAARK_LLAMA_API_KEY_FILE"
  printf ' --host 127.0.0.1 --port %q --ctx-size %q --parallel %q' \
    "$OVERSEAARK_LLAMA_PORT" "$OVERSEAARK_LLAMA_CONTEXT_SIZE" "$OVERSEAARK_LLAMA_PARALLEL"
  printf ' --gpu-layers all --flash-attn on --jinja --reasoning off'
  printf ' --no-webui --metrics --cache-prompt --no-mmap\n'
}

wait_for_llama() {
  local deadline=$((SECONDS + OVERSEAARK_LLAMA_STARTUP_TIMEOUT))
  local last_notice=-1 pid
  while (( SECONDS < deadline )); do
    if llama_health; then
      log "llama.cpp health check passed"
      return 0
    fi
    pid="$(read_pid llm || true)"
    if [[ -n "$pid" ]] && ! pid_alive "$pid"; then
      warn "llama.cpp exited during startup"
      tail -n 160 "$OVERSEAARK_LOG_DIR/llm.log" >&2 2>/dev/null || true
      return 1
    fi
    if (( SECONDS / 15 != last_notice )); then
      last_notice=$((SECONDS / 15))
      log "waiting for llama.cpp model load (${SECONDS}s elapsed)"
    fi
    sleep 2
  done
  warn "llama.cpp did not become healthy within ${OVERSEAARK_LLAMA_STARTUP_TIMEOUT}s"
  tail -n 160 "$OVERSEAARK_LOG_DIR/llm.log" >&2 2>/dev/null || true
  return 1
}

start_llama() {
  [[ -f "$OVERSEAARK_LLAMA_MODEL" ]] || \
    die "Qwen3.6 GGUF is missing at $OVERSEAARK_LLAMA_MODEL; run ./overseaark models sync"
  [[ -f "$OVERSEAARK_LLAMA_MMPROJ" ]] || \
    die "Qwen3.6 mmproj is missing at $OVERSEAARK_LLAMA_MMPROJ; run ./overseaark models sync"
  llama_install_ready || die "pinned CUDA llama.cpp is missing; run ./overseaark bootstrap"
  ensure_llama_api_key
  if llama_health; then
    log "llama.cpp already healthy"
    return 0
  fi

  local stale command
  stale="$(read_pid llm || true)"
  if pid_alive "$stale"; then
    stop_one llm
  else
    remove_pid llm
  fi
  command="$(llama_command)"
  start_one llm "$command" "$REPO_DIR"
  wait_for_llama
}

stop_llama() {
  stop_one llm
}

status_llama() {
  local pid
  pid="$(read_pid llm || true)"
  if llama_health; then
    printf '%-10s healthy pid=%s engine=llama.cpp@%s bind=127.0.0.1:%s\n' \
      "llm" "$pid" "${OVERSEAARK_LLAMA_REVISION:0:8}" "$OVERSEAARK_LLAMA_PORT"
  elif pid_alive "$pid"; then
    printf '%-10s loading pid=%s engine=llama.cpp@%s\n' "llm" "$pid" "${OVERSEAARK_LLAMA_REVISION:0:8}"
  else
    printf '%-10s stopped engine=llama.cpp@%s\n' "llm" "${OVERSEAARK_LLAMA_REVISION:0:8}"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-status}" in
    install) install_llama_cpp ;;
    health) llama_health ;;
    status) status_llama ;;
    *) die "llama-server command must be install, health, or status" 64 ;;
  esac
fi
