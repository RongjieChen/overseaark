#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

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
    cd "$cwd"
    nohup bash -lc "$command" >> "$OVERSEAARK_LOG_DIR/$name.log" 2>&1 &
    write_pid "$name" "$!"
  )
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
  [[ "$OVERSEAARK_HOST" == "127.0.0.1" || "$OVERSEAARK_HOST" == "localhost" ]] || \
    die "start refuses non-localhost bind: $OVERSEAARK_HOST"
  if ! is_truthy "$OVERSEAARK_MOCK_MODE" && ! is_truthy "$OVERSEAARK_SKIP_MODELS"; then
    bash "$SCRIPT_DIR/models.sh" verify
  fi
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

  local frontend
  if frontend="$(frontend_cmd)"; then
    log "frontend static assets are built and served by FastAPI/runtime integration"
  else
    warn "frontend dist not present; run ./overseaark bootstrap to build it"
  fi
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
