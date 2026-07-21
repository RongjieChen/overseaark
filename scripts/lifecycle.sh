#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

models_script="${OVERSEAARK_MODELS_SCRIPT:-$SCRIPT_DIR/models.sh}"
bootstrap_script="${OVERSEAARK_BOOTSTRAP_SCRIPT:-$SCRIPT_DIR/bootstrap.sh}"

backend_cmd() {
  local py
  py="$(python_bin)" || die "python3 or .venv/bin/python is required"

  if [[ -f "$REPO_DIR/backend/app/main.py" ]] && "$py" -c 'import uvicorn' >/dev/null 2>&1; then
    printf '%q -m uvicorn app.main:app --host %q --port %q' "$py" "$OVERSEAARK_HOST" "$OVERSEAARK_BACKEND_PORT"
  elif [[ -f "$REPO_DIR/backend/main.py" ]] && "$py" -c 'import uvicorn' >/dev/null 2>&1; then
    printf '%q -m uvicorn main:app --host %q --port %q' "$py" "$OVERSEAARK_HOST" "$OVERSEAARK_BACKEND_PORT"
  elif [[ -f "$REPO_DIR/backend/pyproject.toml" ]] && have uv; then
    if [[ -f "$REPO_DIR/backend/app/main.py" ]]; then
      printf 'uv run --with fastapi --with pydantic --with python-multipart --with uvicorn[standard] python -m uvicorn app.main:app --host %q --port %q' "$OVERSEAARK_HOST" "$OVERSEAARK_BACKEND_PORT"
    elif [[ -f "$REPO_DIR/backend/main.py" ]]; then
      printf 'uv run --with fastapi --with pydantic --with python-multipart --with uvicorn[standard] python -m uvicorn main:app --host %q --port %q' "$OVERSEAARK_HOST" "$OVERSEAARK_BACKEND_PORT"
    else
      die "backend pyproject exists but no FastAPI entrypoint was found"
    fi
  elif [[ -f "$REPO_DIR/backend/main.py" ]]; then
    printf '%q -m uvicorn main:app --host %q --port %q' "$py" "$OVERSEAARK_HOST" "$OVERSEAARK_BACKEND_PORT"
  elif [[ -f "$REPO_DIR/backend/app/main.py" ]]; then
    printf '%q -m uvicorn app.main:app --host %q --port %q' "$py" "$OVERSEAARK_HOST" "$OVERSEAARK_BACKEND_PORT"
  elif is_truthy "$OVERSEAARK_MOCK_MODE"; then
    printf '%q -m http.server %q --bind %q' "$py" "$OVERSEAARK_BACKEND_PORT" "$OVERSEAARK_HOST"
  else
    die "No FastAPI entrypoint found. Expected backend/main.py or backend/app/main.py. Set OVERSEAARK_MOCK_MODE=1 for local smoke mode."
  fi
}

frontend_cmd() {
  local py
  py="$(python_bin)" || return 1

  if [[ -d "$REPO_DIR/runtime/frontend-dist" || -d "$REPO_DIR/frontend/dist" ]]; then
    return 0
  else
    return 1
  fi
}

command_program() {
  local command="$1"
  local program
  read -r program _ <<< "$command"
  [[ -n "$program" ]] || return 1
  if [[ "$program" == /* ]]; then
    [[ -x "$program" ]] || return 1
  else
    have "$program" || return 1
  fi
  printf '%s\n' "$program"
}

python_command_imports() {
  local command="$1"
  local imports="$2"
  local program
  program="$(command_program "$command")" || return 1
  [[ "$(basename "$program")" == python* ]] || return 0
  "$program" -c "$imports" >/dev/null 2>&1
}

runtime_dependencies_ready() {
  local py
  py="$(python_bin)" || return 1
  if [[ -f "$REPO_DIR/backend/app/main.py" ]]; then
    (cd "$REPO_DIR/backend" && "$py" -c 'import app, fastapi, multipart, pydantic, uvicorn') >/dev/null 2>&1 || return 1
  fi
  [[ -f "$REPO_DIR/runtime/frontend-dist/index.html" ]] || return 1

  if [[ "$OVERSEAARK_ADAPTER_MODE" != "command" ]]; then
    return 0
  fi

  have ffmpeg || return 1
  local_runtime_env
  [[ -x "${OVERSEAARK_LLAMA_CLI:-/root/llama.cpp/build/bin/llama-cli}" ]] || return 1
  command_program "$OVERSEAARK_LLM_COMMAND" >/dev/null || return 1
  python_command_imports "$OVERSEAARK_IMAGE_COMMAND" \
    'import torch, PIL; from diffusers import Step1XEditPipelineV1P2' || return 1
  python_command_imports "$OVERSEAARK_VIDEO_COMMAND" 'import cosmos_framework' || return 1
  python_command_imports "$OVERSEAARK_ASR_COMMAND" 'import nemo.collections.asr, soundfile' || return 1
  python_command_imports "$OVERSEAARK_TTS_COMMAND" 'import nemo.collections.tts, soundfile' || return 1
}

ensure_runtime_dependencies() {
  runtime_dependencies_ready && return 0
  is_truthy "$OVERSEAARK_AUTO_BOOTSTRAP" || \
    die "runtime dependencies are incomplete and OVERSEAARK_AUTO_BOOTSTRAP=0"
  is_truthy "$OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP" || \
    die "runtime dependencies are incomplete and network bootstrap is disabled"
  [[ -f "$bootstrap_script" ]] || die "bootstrap script not found: $bootstrap_script"
  log "runtime dependencies are incomplete; running resumable bootstrap"
  OVERSEAARK_SKIP_MODELS=1 OVERSEAARK_OPERATION_LOCK_HELD=1 bash "$bootstrap_script"
  runtime_dependencies_ready || die "bootstrap finished but runtime dependency preflight still fails"
}

ensure_models() {
  if is_truthy "$OVERSEAARK_MOCK_MODE" || is_truthy "$OVERSEAARK_SKIP_MODELS"; then
    return 0
  fi
  [[ -f "$models_script" ]] || die "model manager script not found: $models_script"
  if bash "$models_script" verify; then
    return 0
  fi
  is_truthy "$OVERSEAARK_AUTO_DOWNLOAD_MODELS" || \
    die "model verification failed and OVERSEAARK_AUTO_DOWNLOAD_MODELS=0"
  log "model files are missing or invalid; downloading only incomplete locked files"
  OVERSEAARK_OPERATION_LOCK_HELD=1 bash "$models_script" sync
}

wait_for_backend() {
  local deadline=$((SECONDS + OVERSEAARK_STARTUP_TIMEOUT))
  if have curl; then
    while (( SECONDS < deadline )); do
      if curl -fsS --max-time 2 \
        "http://${OVERSEAARK_HOST}:${OVERSEAARK_BACKEND_PORT}/api/v1/health" >/dev/null 2>&1; then
        log "backend health check passed"
        return 0
      fi
      sleep 1
    done
  else
    sleep 2
    local pid
    pid="$(read_pid backend || true)"
    pid_alive "$pid" && return 0
  fi
  warn "backend did not become healthy within ${OVERSEAARK_STARTUP_TIMEOUT}s"
  tail -n 40 "$OVERSEAARK_LOG_DIR/backend.log" >&2 2>/dev/null || true
  return 1
}

start_one() {
  local name="$1"
  local command="$2"
  local cwd="${3:-$REPO_DIR}"
  local existing
  existing="$(read_pid "$name" || true)"

  if pid_alive "$existing"; then
    log "$name already running pid=$existing"
    return 0
  fi

  ensure_dirs
  local_runtime_env
  log "starting $name"
  (
    # Keep the parent lock through the health check without leaking its flock
    # descriptor into the long-running backend.
    if [[ "${OVERSEAARK_OPERATION_LOCK_KIND:-}" == "flock" ]] && \
        [[ "${OVERSEAARK_OPERATION_LOCK_FD:-}" =~ ^[0-9]+$ ]]; then
      eval "exec ${OVERSEAARK_OPERATION_LOCK_FD}>&-"
    fi
    cd "$cwd"
    nohup bash -lc "$command" >> "$OVERSEAARK_LOG_DIR/$name.log" 2>&1 &
    write_pid "$name" "$!"
  )
}

validate_startup_configuration() {
  [[ "$OVERSEAARK_STARTUP_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || \
    die "OVERSEAARK_STARTUP_TIMEOUT must be a positive integer"
  [[ "$OVERSEAARK_BACKEND_PORT" =~ ^[1-9][0-9]*$ ]] && \
    (( OVERSEAARK_BACKEND_PORT <= 65535 )) || \
    die "OVERSEAARK_BACKEND_PORT must be an integer from 1 to 65535"
}

stop_one() {
  local name="$1"
  local pid
  pid="$(read_pid "$name" || true)"

  if ! pid_alive "$pid"; then
    remove_pid "$name"
    log "$name stopped"
    return 0
  fi

  log "stopping $name pid=$pid"
  kill "$pid" || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! pid_alive "$pid"; then
      remove_pid "$name"
      log "$name stopped"
      return 0
    fi
    sleep 1
  done
  kill -TERM "$pid" || true
  sleep 1
  if pid_alive "$pid"; then
    kill -KILL "$pid" || true
  fi
  remove_pid "$name"
}

status_one() {
  local name="$1"
  local pid
  pid="$(read_pid "$name" || true)"
  if pid_alive "$pid"; then
    printf '%-10s running pid=%s\n' "$name" "$pid"
  else
    printf '%-10s stopped\n' "$name"
  fi
}

start_all() {
  validate_startup_configuration
  [[ "$OVERSEAARK_HOST" == "127.0.0.1" || "$OVERSEAARK_HOST" == "localhost" ]] || \
    die "start refuses non-localhost bind: $OVERSEAARK_HOST"
  acquire_operation_lock bootstrap
  trap release_operation_lock EXIT
  ensure_runtime_dependencies
  ensure_models
  local backend
  backend="$(backend_cmd)"
  if [[ "$OVERSEAARK_ADAPTER_MODE" == "command" ]]; then
    local_runtime_env
    for var in OVERSEAARK_LLM_COMMAND OVERSEAARK_IMAGE_COMMAND OVERSEAARK_VIDEO_COMMAND OVERSEAARK_ASR_COMMAND OVERSEAARK_TTS_COMMAND; do
      [[ -n "${!var:-}" ]] || die "command mode requires $var"
    done
    validate_offline_runtime
  else
    export OVERSEAARK_ADAPTER_MODE=mock
    export OVERSEAARK_MOCK_MODE=1
    warn "starting backend in mock adapter mode; set OVERSEAARK_ADAPTER_MODE=command for local heavy adapters"
  fi
  if [[ -d "$REPO_DIR/backend" ]]; then
    start_one backend "$backend" "${REPO_DIR}/backend"
  else
    start_one backend "$backend" "$REPO_DIR"
  fi
  wait_for_backend || die "backend startup failed; inspect ./overseaark logs backend"

  local frontend
  if frontend="$(frontend_cmd)"; then
    log "frontend static assets are built and served by FastAPI/runtime integration"
  else
    die "frontend dist is missing after startup preflight"
  fi
  release_operation_lock
  trap - EXIT
}

stop_all() {
  stop_one frontend
  stop_one backend
}

show_logs() {
  local target="${1:-all}"
  case "$target" in
    backend|frontend)
      touch "$OVERSEAARK_LOG_DIR/$target.log"
      exec tail -n 80 -f "$OVERSEAARK_LOG_DIR/$target.log"
      ;;
    all)
      touch "$OVERSEAARK_LOG_DIR/backend.log" "$OVERSEAARK_LOG_DIR/frontend.log"
      exec tail -n 80 -f "$OVERSEAARK_LOG_DIR/backend.log" "$OVERSEAARK_LOG_DIR/frontend.log"
      ;;
    *)
      die "logs target must be backend, frontend, or all" 64
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-status}" in
    start) start_all ;;
    stop) stop_all ;;
    restart) stop_all; start_all ;;
    status)
      ensure_dirs
      printf 'root       %s\n' "$OVERSEAARK_ROOT"
      printf 'models     %s\n' "$OVERSEAARK_MODELS_DIR"
      printf 'data       %s\n' "$OVERSEAARK_DATA_DIR"
      printf 'bind       %s:%s\n' "$OVERSEAARK_HOST" "$OVERSEAARK_BACKEND_PORT"
      status_one backend
      if [[ -d "$REPO_DIR/runtime/frontend-dist" || -d "$REPO_DIR/frontend/dist" ]]; then
        printf '%-10s built\n' "frontend"
      else
        printf '%-10s missing-dist\n' "frontend"
      fi
      ;;
    logs) shift || true; show_logs "${1:-all}" ;;
    *) die "unknown lifecycle command: ${1:-}" 64 ;;
  esac
fi
