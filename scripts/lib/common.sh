#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

load_env() {
  if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
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
  export OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP="${OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP:-1}"
  export OVERSEAARK_SYNC_OPTIONAL_MODELS="${OVERSEAARK_SYNC_OPTIONAL_MODELS:-0}"
  export OVERSEAARK_ADAPTER_MODE="${OVERSEAARK_ADAPTER_MODE:-$default_adapter_mode}"
  export MODELSCOPE_ENDPOINT="${MODELSCOPE_ENDPOINT:-https://modelscope.cn}"
  export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
}

ensure_dirs() {
  mkdir -p "$OVERSEAARK_MODELS_DIR" "$OVERSEAARK_DATA_DIR" "$OVERSEAARK_LOG_DIR" "$OVERSEAARK_PID_DIR"
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
