#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

load_env() {
  if [[ -f "$REPO_DIR/.env" ]]; then
    # Shell-provided values take precedence over the deployment file. This is
    # required for safe one-off mock tests and maintenance commands on a host
    # whose persistent .env selects command-mode inference.
    local override_names=(
      OVERSEAARK_ROOT OVERSEAARK_MODELS_DIR OVERSEAARK_DATA_DIR
      OVERSEAARK_LOG_DIR OVERSEAARK_PID_DIR OVERSEAARK_HOST
      OVERSEAARK_BACKEND_PORT OVERSEAARK_FRONTEND_PORT
      OVERSEAARK_SKIP_MODELS OVERSEAARK_MOCK_MODE
      OVERSEAARK_AUTO_BOOTSTRAP OVERSEAARK_AUTO_DOWNLOAD_MODELS
      OVERSEAARK_STARTUP_TIMEOUT
      OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP OVERSEAARK_SYNC_OPTIONAL_MODELS
      OVERSEAARK_PYPI_INDEX OVERSEAARK_PYPI_FILE_PREFIX
      OVERSEAARK_GITHUB_GIT_PREFIX
      OVERSEAARK_GITHUB_ASSET_PREFIX
      OVERSEAARK_ADAPTER_MODE OVERSEAARK_ALLOW_DEGRADED_VIDEO
      OVERSEAARK_ADAPTER_TIMEOUT OVERSEAARK_BENCH_TIMEOUT
      OVERSEAARK_LLM_TOKENS OVERSEAARK_LLM_TIMEOUT
      OVERSEAARK_VLLM_VERSION OVERSEAARK_VLLM_WHEEL_URL
      OVERSEAARK_VLLM_WHEEL_SHA256 OVERSEAARK_VLLM_PYTHON
      OVERSEAARK_VLLM_BIN OVERSEAARK_VLLM_MODEL_DIR
      OVERSEAARK_VLLM_SERVED_MODEL OVERSEAARK_VLLM_PORT
      OVERSEAARK_VLLM_STARTUP_TIMEOUT OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION
      OVERSEAARK_VLLM_MAX_MODEL_LEN OVERSEAARK_VLLM_MAX_NUM_SEQS
      OVERSEAARK_LLM_BASE_URL OVERSEAARK_PYTORCH_INDEX
      MODELSCOPE_ENDPOINT HF_ENDPOINT TRANSFORMERS_OFFLINE
      HF_HUB_OFFLINE HF_DATASETS_OFFLINE NO_PROXY no_proxy
    )
    local saved_names=() saved_values=() name index
    for name in "${override_names[@]}"; do
      if printenv "$name" >/dev/null 2>&1; then
        saved_names+=("$name")
        saved_values+=("${!name}")
      fi
    done
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
    for index in "${!saved_names[@]}"; do
      printf -v "${saved_names[$index]}" '%s' "${saved_values[$index]}"
      export "${saved_names[$index]}"
    done
  fi

  local default_models_dir="$REPO_DIR/overseaark-models"
  local default_data_dir="$REPO_DIR/overseaark-data"
  local default_adapter_mode="mock"
  if [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "aarch64" ]] && have nvidia-smi; then
    default_models_dir="/home/Developer/overseaark-models"
    default_data_dir="/home/Developer/overseaark-data"
    default_adapter_mode="command"
  fi
  export OVERSEAARK_ROOT="${OVERSEAARK_ROOT:-$REPO_DIR}"
  export OVERSEAARK_MODELS_DIR="${OVERSEAARK_MODELS_DIR:-$default_models_dir}"
  export OVERSEAARK_DATA_DIR="${OVERSEAARK_DATA_DIR:-$default_data_dir}"
  export OVERSEAARK_LOG_DIR="${OVERSEAARK_LOG_DIR:-$OVERSEAARK_DATA_DIR/logs}"
  export OVERSEAARK_PID_DIR="${OVERSEAARK_PID_DIR:-$OVERSEAARK_DATA_DIR/run}"
  export OVERSEAARK_HOST="${OVERSEAARK_HOST:-127.0.0.1}"
  export OVERSEAARK_BACKEND_PORT="${OVERSEAARK_BACKEND_PORT:-8000}"
  export OVERSEAARK_FRONTEND_PORT="${OVERSEAARK_FRONTEND_PORT:-3000}"
  export OVERSEAARK_SKIP_MODELS="${OVERSEAARK_SKIP_MODELS:-0}"
  export OVERSEAARK_MOCK_MODE="${OVERSEAARK_MOCK_MODE:-0}"
  export OVERSEAARK_AUTO_BOOTSTRAP="${OVERSEAARK_AUTO_BOOTSTRAP:-1}"
  export OVERSEAARK_AUTO_DOWNLOAD_MODELS="${OVERSEAARK_AUTO_DOWNLOAD_MODELS:-1}"
  export OVERSEAARK_STARTUP_TIMEOUT="${OVERSEAARK_STARTUP_TIMEOUT:-90}"
  export OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP="${OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP:-1}"
  export OVERSEAARK_SYNC_OPTIONAL_MODELS="${OVERSEAARK_SYNC_OPTIONAL_MODELS:-0}"
  export OVERSEAARK_ADAPTER_MODE="${OVERSEAARK_ADAPTER_MODE:-$default_adapter_mode}"
  export OVERSEAARK_PYPI_INDEX="${OVERSEAARK_PYPI_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
  export OVERSEAARK_PYPI_FILE_PREFIX="${OVERSEAARK_PYPI_FILE_PREFIX-https://mirrors.aliyun.com/pypi/}"
  export OVERSEAARK_GITHUB_GIT_PREFIX="${OVERSEAARK_GITHUB_GIT_PREFIX-https://gh-proxy.com/https://github.com/}"
  export OVERSEAARK_GITHUB_ASSET_PREFIX="${OVERSEAARK_GITHUB_ASSET_PREFIX-https://ghfast.top/}"
  export OVERSEAARK_VLLM_VERSION="${OVERSEAARK_VLLM_VERSION:-0.25.1}"
  export OVERSEAARK_VLLM_WHEEL_URL="${OVERSEAARK_VLLM_WHEEL_URL:-https://github.com/vllm-project/vllm/releases/download/v0.25.1/vllm-0.25.1%2Bcu129-cp38-abi3-manylinux_2_28_aarch64.whl}"
  export OVERSEAARK_VLLM_WHEEL_SHA256="${OVERSEAARK_VLLM_WHEEL_SHA256:-bdffbe35b2c1ab8f2a9dcc337b657261d9b192c92c217e5a2f98a8835fe78daa}"
  export OVERSEAARK_VLLM_PYTHON="${OVERSEAARK_VLLM_PYTHON:-$REPO_DIR/.venv-vllm/bin/python}"
  export OVERSEAARK_VLLM_BIN="${OVERSEAARK_VLLM_BIN:-$REPO_DIR/.venv-vllm/bin/vllm}"
  export OVERSEAARK_VLLM_MODEL_DIR="${OVERSEAARK_VLLM_MODEL_DIR:-$OVERSEAARK_MODELS_DIR/nvidia/qwen3.6-35b-a3b-nvfp4}"
  export OVERSEAARK_VLLM_SERVED_MODEL="${OVERSEAARK_VLLM_SERVED_MODEL:-nvidia/Qwen3.6-35B-A3B-NVFP4}"
  export OVERSEAARK_VLLM_PORT="${OVERSEAARK_VLLM_PORT:-8011}"
  export OVERSEAARK_VLLM_STARTUP_TIMEOUT="${OVERSEAARK_VLLM_STARTUP_TIMEOUT:-900}"
  export OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION="${OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION:-0.4}"
  export OVERSEAARK_VLLM_MAX_MODEL_LEN="${OVERSEAARK_VLLM_MAX_MODEL_LEN:-262144}"
  export OVERSEAARK_VLLM_MAX_NUM_SEQS="${OVERSEAARK_VLLM_MAX_NUM_SEQS:-4}"
  export OVERSEAARK_LLM_BASE_URL="${OVERSEAARK_LLM_BASE_URL:-http://127.0.0.1:$OVERSEAARK_VLLM_PORT}"
  export OVERSEAARK_PYTORCH_INDEX="${OVERSEAARK_PYTORCH_INDEX:-https://mirrors.aliyun.com/pytorch-wheels/cu129}"
  export MODELSCOPE_ENDPOINT="${MODELSCOPE_ENDPOINT:-https://modelscope.cn}"
  export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
}

ensure_dirs() {
  mkdir -p "$OVERSEAARK_MODELS_DIR" "$OVERSEAARK_DATA_DIR" "$OVERSEAARK_LOG_DIR" "$OVERSEAARK_PID_DIR"
}

acquire_operation_lock() {
  local name="${1:-bootstrap}"
  ensure_dirs
  if have flock; then
    exec {OVERSEAARK_OPERATION_LOCK_FD}>"$OVERSEAARK_PID_DIR/$name.lock"
    flock -n "$OVERSEAARK_OPERATION_LOCK_FD" || \
      die "another start/bootstrap operation is already running"
    OVERSEAARK_OPERATION_LOCK_KIND="flock"
    return 0
  fi

  local lock_path="$OVERSEAARK_PID_DIR/$name.lock.owner"
  if ! ln -s "$$" "$lock_path" 2>/dev/null; then
    local owner=""
    owner="$(readlink "$lock_path" 2>/dev/null || true)"
    if pid_alive "$owner"; then
      die "another start/bootstrap operation is already running pid=$owner"
    fi
    rm -f "$lock_path"
    ln -s "$$" "$lock_path" 2>/dev/null || \
      die "failed to acquire operation lock: $lock_path"
  fi
  OVERSEAARK_OPERATION_LOCK_KIND="symlink"
  OVERSEAARK_OPERATION_LOCK_PATH="$lock_path"
}

release_operation_lock() {
  if [[ "${OVERSEAARK_OPERATION_LOCK_KIND:-}" == "flock" ]] && \
      [[ -n "${OVERSEAARK_OPERATION_LOCK_FD:-}" ]] && have flock; then
    flock -u "$OVERSEAARK_OPERATION_LOCK_FD" || true
    [[ "$OVERSEAARK_OPERATION_LOCK_FD" =~ ^[0-9]+$ ]] && \
      eval "exec ${OVERSEAARK_OPERATION_LOCK_FD}>&-"
    unset OVERSEAARK_OPERATION_LOCK_FD
  fi
  if [[ "${OVERSEAARK_OPERATION_LOCK_KIND:-}" == "symlink" ]] && \
      [[ -n "${OVERSEAARK_OPERATION_LOCK_PATH:-}" ]]; then
    if [[ "$(readlink "$OVERSEAARK_OPERATION_LOCK_PATH" 2>/dev/null || true)" == "$$" ]]; then
      rm -f "$OVERSEAARK_OPERATION_LOCK_PATH"
    fi
    unset OVERSEAARK_OPERATION_LOCK_PATH
  fi
  unset OVERSEAARK_OPERATION_LOCK_KIND
}

log() {
  printf '[overseaark] %s\n' "$*"
}

warn() {
  printf '[overseaark][warn] %s\n' "$*" >&2
}

die() {
  printf '[overseaark][error] %s\n' "$*" >&2
  exit "${2:-1}"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

read_pid() {
  local name="$1"
  local file="$OVERSEAARK_PID_DIR/$name.pid"
  [[ -f "$file" ]] && sed -n '1p' "$file"
}

write_pid() {
  local name="$1"
  local pid="$2"
  printf '%s\n' "$pid" > "$OVERSEAARK_PID_DIR/$name.pid"
}

remove_pid() {
  local name="$1"
  rm -f "$OVERSEAARK_PID_DIR/$name.pid"
}

python_bin() {
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$REPO_DIR/.venv/bin/python"
  elif [[ -x "$REPO_DIR/backend/.venv/bin/python" ]]; then
    printf '%s\n' "$REPO_DIR/backend/.venv/bin/python"
  elif have python3; then
    command -v python3
  else
    return 1
  fi
}

npm_bin() {
  if have npm; then
    command -v npm
  else
    return 1
  fi
}

local_runtime_env() {
  export OVERSEAARK_MODEL_ROOT="$OVERSEAARK_MODELS_DIR"
  export OVERSEAARK_DATA_ROOT="$OVERSEAARK_DATA_DIR"
  export OVERSEAARK_DATA_DIR="$OVERSEAARK_DATA_DIR"
  export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
  export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
  export HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"
  export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
  export no_proxy="${no_proxy:-127.0.0.1,localhost}"
  if [[ "$OVERSEAARK_ADAPTER_MODE" == "command" ]]; then
    export OVERSEAARK_LLM_COMMAND="${OVERSEAARK_LLM_COMMAND:-/usr/bin/env python3 $SCRIPT_DIR/adapters/llm_step.py}"
    export OVERSEAARK_IMAGE_COMMAND="${OVERSEAARK_IMAGE_COMMAND:-$REPO_DIR/.venv-step1x/bin/python $SCRIPT_DIR/adapters/image_step1x.py}"
    export OVERSEAARK_VIDEO_COMMAND="${OVERSEAARK_VIDEO_COMMAND:-$REPO_DIR/vendor/cosmos-framework/.venv/bin/python $SCRIPT_DIR/adapters/video_cosmos3.py}"
    export OVERSEAARK_ASR_COMMAND="${OVERSEAARK_ASR_COMMAND:-$REPO_DIR/.venv-nemo/bin/python $SCRIPT_DIR/adapters/asr_nemo.py}"
    export OVERSEAARK_TTS_COMMAND="${OVERSEAARK_TTS_COMMAND:-$REPO_DIR/.venv-nemo/bin/python $SCRIPT_DIR/adapters/tts_magpie.py}"
  fi
}

validate_offline_runtime() {
  [[ "$OVERSEAARK_HOST" == "127.0.0.1" || "$OVERSEAARK_HOST" == "localhost" ]] || \
    die "runtime bind must remain localhost-only, got $OVERSEAARK_HOST"
  [[ "${HF_HUB_OFFLINE:-1}" == "1" && "${TRANSFORMERS_OFFLINE:-1}" == "1" ]] || \
    die "command mode requires HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1"
  [[ "$OVERSEAARK_LLM_BASE_URL" == "http://127.0.0.1:$OVERSEAARK_VLLM_PORT" || \
     "$OVERSEAARK_LLM_BASE_URL" == "http://localhost:$OVERSEAARK_VLLM_PORT" ]] || \
    die "LLM server URL must remain localhost-only, got $OVERSEAARK_LLM_BASE_URL"
  local command
  for command in \
    "${OVERSEAARK_LLM_COMMAND:-}" \
    "${OVERSEAARK_IMAGE_COMMAND:-}" \
    "${OVERSEAARK_VIDEO_COMMAND:-}" \
    "${OVERSEAARK_ASR_COMMAND:-}" \
    "${OVERSEAARK_TTS_COMMAND:-}"; do
    [[ "$command" != *"http://"* && "$command" != *"https://"* ]] || \
      die "remote model command URLs are forbidden during offline inference"
  done
}

load_env
