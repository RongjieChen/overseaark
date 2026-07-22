#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$SCRIPT_DIR/vllm_server.sh"

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
  frontend_dist_ready
}

frontend_dist_ready() {
  local dist_index="$REPO_DIR/runtime/frontend-dist/index.html"
  [[ -f "$dist_index" ]] || return 1
  local demo_relative="demo/portable-smart-espresso-maker.png"
  local demo_source="$REPO_DIR/frontend/public/$demo_relative"
  local demo_dist="$REPO_DIR/runtime/frontend-dist/$demo_relative"
  [[ -f "$demo_source" && -f "$demo_dist" ]] || return 1
  cmp -s "$demo_source" "$demo_dist" || return 1

  local source
  for source in \
    "$REPO_DIR/frontend/index.html" \
    "$REPO_DIR/frontend/package.json" \
    "$REPO_DIR/frontend/package-lock.json" \
    "$REPO_DIR/frontend/pnpm-lock.yaml" \
    "$REPO_DIR/frontend/vite.config.ts" \
    "$REPO_DIR/frontend"/tsconfig*.json; do
    if [[ -f "$source" && "$source" -nt "$dist_index" ]]; then
      return 1
    fi
  done

  if [[ -d "$REPO_DIR/frontend/src" ]] && \
      find "$REPO_DIR/frontend/src" -type f -newer "$dist_index" -print -quit | grep -q .; then
    return 1
  fi

  if [[ -d "$REPO_DIR/frontend/public" ]] && \
      find "$REPO_DIR/frontend/public" -type f -newer "$dist_index" -print -quit | grep -q .; then
    return 1
  fi

  return 0
}

frontend_build_dependencies_ready() {
  [[ -f "$REPO_DIR/frontend/package.json" ]] || return 1
  [[ -d "$REPO_DIR/frontend/node_modules" ]] || return 1

  if [[ -f "$REPO_DIR/frontend/pnpm-lock.yaml" ]]; then
    [[ -f "$REPO_DIR/frontend/node_modules/.pnpm/lock.yaml" ]] || return 1
    [[ ! "$REPO_DIR/frontend/pnpm-lock.yaml" -nt "$REPO_DIR/frontend/node_modules/.pnpm/lock.yaml" ]] || return 1
    have pnpm
  else
    if [[ -f "$REPO_DIR/frontend/package-lock.json" ]]; then
      [[ -f "$REPO_DIR/frontend/node_modules/.package-lock.json" ]] || return 1
      [[ ! "$REPO_DIR/frontend/package-lock.json" -nt "$REPO_DIR/frontend/node_modules/.package-lock.json" ]] || return 1
    fi
    npm_bin >/dev/null
  fi
}

build_frontend_assets() {
  if [[ -f "$REPO_DIR/frontend/pnpm-lock.yaml" ]]; then
    (cd "$REPO_DIR/frontend" && pnpm run build)
  else
    local npm
    npm="$(npm_bin)" || return 1
    (cd "$REPO_DIR/frontend" && "$npm" run build)
  fi
}

ensure_frontend_assets() {
  frontend_dist_ready && return 0

  if frontend_build_dependencies_ready; then
    log "frontend sources are newer than runtime assets; rebuilding locally"
    build_frontend_assets || die "frontend build failed"
  else
    is_truthy "$OVERSEAARK_AUTO_BOOTSTRAP" || \
      die "frontend build dependencies are incomplete and OVERSEAARK_AUTO_BOOTSTRAP=0"
    is_truthy "$OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP" || \
      die "frontend build dependencies are incomplete and network bootstrap is disabled"
    [[ -f "$bootstrap_script" ]] || die "bootstrap script not found: $bootstrap_script"
    log "frontend build dependencies are incomplete; running resumable bootstrap"
    OVERSEAARK_SKIP_MODELS=1 OVERSEAARK_OPERATION_LOCK_HELD=1 bash "$bootstrap_script"
  fi

  frontend_dist_ready || die "frontend build completed without fresh runtime assets"
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
  have ffmpeg || return 1

  if [[ "$OVERSEAARK_ADAPTER_MODE" != "command" ]]; then
    return 0
  fi

  local_runtime_env
  vllm_install_ready || return 1
  command_program "$OVERSEAARK_LLM_COMMAND" >/dev/null || return 1
  python_command_imports "$OVERSEAARK_IMAGE_COMMAND" \
    'import torch, PIL; from diffusers import Step1XEditPipelineV1P2' || return 1
  python_command_imports "$OVERSEAARK_VIDEO_COMMAND" 'import cosmos_framework' || return 1
  python_command_imports "$OVERSEAARK_ASR_COMMAND" 'import nemo.collections.asr, soundfile' || return 1
  python_command_imports "$OVERSEAARK_TTS_COMMAND" \
    'import pathlib, pyopenjtalk, nemo.collections.tts, soundfile; assert pathlib.Path(pyopenjtalk.OPEN_JTALK_DICT_DIR.decode()).is_dir()' || return 1
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
  local existing existing_identity
  existing="$(read_pid "$name" || true)"

  if pid_alive "$existing"; then
    local existing_pgid
    existing_identity="$(read_pid_identity "$name" || true)"
    existing_pgid="$(read_pgid "$name" || true)"
    if ! process_identity_matches "$existing" "$existing_identity"; then
      die "$name PID state is missing, stale, or reused; refusing to replace a live unverified process"
    fi
    if [[ -n "$existing_pgid" ]]; then
      log "$name already running pid=$existing pgid=$existing_pgid"
    else
      log "$name already running pid=$existing"
    fi
    return 0
  fi

  ensure_dirs
  remove_process_state "$name"
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
    local launched_pid launched_pgid="" launched_identity launch_state
    if [[ "$(uname -s)" == "Linux" ]] && have setsid; then
      # The session leader reports its own PID/PGID after setsid. This remains
      # correct even when util-linux setsid must fork because its caller was a
      # process-group leader; relying on the outer shell's $! would not.
      launch_state="$OVERSEAARK_PID_DIR/$name.launch.$$"
      nohup setsid bash -c '
        own_pgid="$(ps -o pgid= -p "$$" 2>/dev/null | awk '\''NR == 1 { gsub(/[[:space:]]/, ""); print }'\'')"
        printf "%s %s\n" "$$" "$own_pgid" > "$1"
        exec bash -lc "$2"
      ' overseaark-session "$launch_state" "$command" >> "$OVERSEAARK_LOG_DIR/$name.log" 2>&1 &
      local launcher_pid="$!"
      for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        if [[ -s "$launch_state" ]]; then
          read -r launched_pid launched_pgid < "$launch_state"
          [[ "$launched_pid" =~ ^[1-9][0-9]*$ && "$launched_pgid" == "$launched_pid" ]] && break
        fi
        sleep 0.05
      done
      rm -f "$launch_state"
      if [[ "$launched_pgid" != "$launched_pid" ]]; then
        kill -TERM "$launcher_pid" >/dev/null 2>&1 || true
        wait "$launcher_pid" 2>/dev/null || true
        die "$name failed to enter an isolated process group"
      fi
      write_pgid "$name" "$launched_pgid"
    else
      # macOS does not ship setsid. Keep the PID-only fallback deliberately
      # group-less so stop can never signal the lifecycle caller's group.
      nohup bash -lc "$command" >> "$OVERSEAARK_LOG_DIR/$name.log" 2>&1 &
      launched_pid="$!"
    fi
    launched_identity="$(process_identity "$launched_pid" || true)"
    if [[ -z "$launched_identity" ]]; then
      if [[ -n "$launched_pgid" && "$launched_pgid" == "$launched_pid" ]]; then
        kill -TERM -- "-$launched_pgid" >/dev/null 2>&1 || true
      else
        kill -TERM "$launched_pid" >/dev/null 2>&1 || true
      fi
      remove_process_state "$name"
      die "$name started without a verifiable process identity"
    fi
    write_pid "$name" "$launched_pid" "$launched_identity"
  )
}

validate_startup_configuration() {
  [[ "$OVERSEAARK_STARTUP_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || \
    die "OVERSEAARK_STARTUP_TIMEOUT must be a positive integer"
  [[ "$OVERSEAARK_VLLM_STARTUP_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || \
    die "OVERSEAARK_VLLM_STARTUP_TIMEOUT must be a positive integer"
  [[ "$OVERSEAARK_BACKEND_PORT" =~ ^[1-9][0-9]*$ ]] && \
    (( OVERSEAARK_BACKEND_PORT <= 65535 )) || \
    die "OVERSEAARK_BACKEND_PORT must be an integer from 1 to 65535"
  [[ "$OVERSEAARK_VLLM_PORT" =~ ^[1-9][0-9]*$ ]] && \
    (( OVERSEAARK_VLLM_PORT <= 65535 )) || \
    die "OVERSEAARK_VLLM_PORT must be an integer from 1 to 65535"
  [[ "$OVERSEAARK_KEEP_VLLM_RESIDENT" =~ ^[01]$ ]] || \
    die "OVERSEAARK_KEEP_VLLM_RESIDENT must be 0 or 1"
  [[ ",$OVERSEAARK_RESIDENT_ADAPTERS," != *",video,"* ]] || \
    die "OVERSEAARK_RESIDENT_ADAPTERS supports only asr, tts, and optional image"
  [[ ",$OVERSEAARK_RESIDENT_ADAPTERS," != *",llm,"* ]] || \
    die "vLLM residency is controlled by OVERSEAARK_KEEP_VLLM_RESIDENT, not OVERSEAARK_RESIDENT_ADAPTERS"
  local resident_name
  local -a resident_names
  IFS=',' read -r -a resident_names <<< "$OVERSEAARK_RESIDENT_ADAPTERS"
  for resident_name in "${resident_names[@]}"; do
    resident_name="${resident_name//[[:space:]]/}"
    case "$resident_name" in
      ""|asr|tts|image) ;;
      *) die "OVERSEAARK_RESIDENT_ADAPTERS supports only asr, tts, and optional image" ;;
    esac
  done
}

stop_one() {
  local name="$1"
  local pid pgid identity caller_pgid root_pgid descendants
  pid="$(read_pid "$name" || true)"
  pgid="$(read_pgid "$name" || true)"
  identity="$(read_pid_identity "$name" || true)"
  caller_pgid="$(process_pgid "$$" || true)"

  if pid_alive "$pid" && ! process_identity_matches "$pid" "$identity"; then
    warn "$name PID state is missing or stale; refusing to signal unverified pid=$pid"
    remove_process_state "$name"
    return 0
  fi

  # A dead session leader does not prove its group is empty: children may keep
  # the original PGID after the leader exits. Its start identity can no longer
  # be revalidated, so retain recovery state and fail closed instead of either
  # signalling an unverified group or falsely reporting it stopped.
  if ! pid_alive "$pid" && [[ "$pgid" =~ ^[1-9][0-9]*$ && "$pgid" == "$pid" ]] && \
     process_group_alive "$pgid"; then
    warn "$name leader pid=$pid exited but recorded pgid=$pgid is still live; retaining state for recovery"
    return 1
  fi

  # Only PGIDs created and recorded by start_one are trusted for group
  # signalling. In particular, never signal the group running this command.
  local safe_recorded_group=""
  if [[ "$pid" =~ ^[1-9][0-9]*$ && "$pgid" == "$pid" && \
        "$caller_pgid" =~ ^[1-9][0-9]*$ && "$pgid" != "$caller_pgid" ]] && \
     process_identity_matches "$pid" "$identity"; then
    safe_recorded_group="$pgid"
  fi

  if ! pid_alive "$pid" && \
      { [[ -z "$safe_recorded_group" ]] || ! process_group_alive "$safe_recorded_group"; }; then
    remove_process_state "$name"
    log "$name stopped"
    return 0
  fi

  # Capture independently-sessioned ResidentCommandAdapter workers before the
  # backend can exit and they are reparented. Only these observed PID/PGID pairs
  # are eligible for signalling below.
  descendants="$(descendant_processes "$pid" || true)"
  root_pgid="$(process_pgid "$pid" || true)"

  if [[ -n "$safe_recorded_group" ]]; then
    log "stopping $name pid=$pid pgid=$safe_recorded_group"
  else
    log "stopping $name pid=$pid"
  fi
  signal_process_tree TERM "$pid" "$identity" "$root_pgid" "$safe_recorded_group" "$caller_pgid" "$descendants"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! process_tree_alive "$pid" "$identity" "$root_pgid" "$safe_recorded_group" "$caller_pgid" "$descendants"; then
      remove_process_state "$name"
      log "$name stopped"
      return 0
    fi
    sleep 1
  done

  warn "$name did not stop gracefully; sending KILL to its confirmed process tree"
  signal_process_tree KILL "$pid" "$identity" "$root_pgid" "$safe_recorded_group" "$caller_pgid" "$descendants"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! process_tree_alive "$pid" "$identity" "$root_pgid" "$safe_recorded_group" "$caller_pgid" "$descendants"; then
      remove_process_state "$name"
      log "$name stopped"
      return 0
    fi
    sleep 0.1
  done
  warn "$name still has a confirmed process after KILL"
  return 1
}

signal_process_tree() {
  local signal="$1"
  local pid="$2"
  local identity="$3"
  local root_pgid="$4"
  local safe_recorded_group="$5"
  local caller_pgid="$6"
  local descendants="$7"
  local child_pid child_pgid child_identity current_pgid

  if [[ -n "$safe_recorded_group" ]] && process_group_alive "$safe_recorded_group"; then
    kill "-$signal" -- "-$safe_recorded_group" >/dev/null 2>&1 || true
  fi

  while read -r child_pid child_pgid child_identity; do
    [[ "$child_pid" =~ ^[1-9][0-9]*$ && "$child_pgid" =~ ^[1-9][0-9]*$ && \
       -n "$child_identity" ]] || continue
    # start_new_session=True makes the worker its group leader. Requiring the
    # observed PGID to equal an observed descendant PID avoids touching an
    # unrelated group even if state files were stale or corrupted.
    if [[ "$child_pgid" == "$child_pid" && \
          "$child_pgid" != "$safe_recorded_group" && \
          "$child_pgid" != "$caller_pgid" ]] && \
         process_identity_matches "$child_pid" "$child_identity" && \
         process_group_alive "$child_pgid"; then
      kill "-$signal" -- "-$child_pgid" >/dev/null 2>&1 || true
    fi
  done <<< "$descendants"

  # Exact-PID signalling covers the no-setsid fallback and descendants sharing
  # their parent's group. Re-check the captured PGID first to reduce PID-reuse
  # risk; never widen this fallback into a group signal.
  while read -r child_pid child_pgid child_identity; do
    [[ "$child_pid" =~ ^[1-9][0-9]*$ && "$child_pgid" =~ ^[1-9][0-9]*$ && \
       -n "$child_identity" ]] || continue
    current_pgid="$(process_pgid "$child_pid" || true)"
    if [[ "$current_pgid" == "$child_pgid" ]] && \
       process_identity_matches "$child_pid" "$child_identity"; then
      kill "-$signal" "$child_pid" >/dev/null 2>&1 || true
    fi
  done <<< "$descendants"

  if [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
    current_pgid="$(process_pgid "$pid" || true)"
    if [[ -n "$root_pgid" && "$current_pgid" == "$root_pgid" ]] && \
       process_identity_matches "$pid" "$identity"; then
      kill "-$signal" "$pid" >/dev/null 2>&1 || true
    fi
  fi
}

process_tree_alive() {
  local pid="$1"
  local identity="$2"
  local root_pgid="$3"
  local safe_recorded_group="$4"
  local caller_pgid="$5"
  local descendants="$6"
  local child_pid child_pgid child_identity current_pgid

  if [[ -n "$safe_recorded_group" ]] && process_group_alive "$safe_recorded_group"; then
    return 0
  fi
  if [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
    current_pgid="$(process_pgid "$pid" || true)"
    [[ -n "$root_pgid" && "$current_pgid" == "$root_pgid" ]] && \
      process_identity_matches "$pid" "$identity" && return 0
  fi
  while read -r child_pid child_pgid child_identity; do
    [[ "$child_pid" =~ ^[1-9][0-9]*$ && "$child_pgid" =~ ^[1-9][0-9]*$ && \
       -n "$child_identity" ]] || continue
    if [[ "$child_pgid" == "$child_pid" && \
          "$child_pgid" != "$safe_recorded_group" && \
          "$child_pgid" != "$caller_pgid" ]] && \
         process_identity_matches "$child_pid" "$child_identity" && \
         process_group_alive "$child_pgid"; then
      return 0
    fi
    current_pgid="$(process_pgid "$child_pid" || true)"
    [[ "$current_pgid" == "$child_pgid" ]] && \
      process_identity_matches "$child_pid" "$child_identity" && return 0
  done <<< "$descendants"
  return 1
}

status_one() {
  local name="$1"
  local pid pgid identity
  pid="$(read_pid "$name" || true)"
  pgid="$(read_pgid "$name" || true)"
  identity="$(read_pid_identity "$name" || true)"
  if pid_alive "$pid" && process_identity_matches "$pid" "$identity"; then
    if [[ -n "$pgid" ]]; then
      printf '%-10s running pid=%s pgid=%s\n' "$name" "$pid" "$pgid"
    else
      printf '%-10s running pid=%s\n' "$name" "$pid"
    fi
  elif pid_alive "$pid"; then
    printf '%-10s stale/unverified pid=%s\n' "$name" "$pid"
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
  ensure_frontend_assets
  ensure_models
  local backend
  backend="$(backend_cmd)"
  if [[ "$OVERSEAARK_ADAPTER_MODE" == "command" ]]; then
    local_runtime_env
    for var in OVERSEAARK_LLM_COMMAND OVERSEAARK_IMAGE_COMMAND OVERSEAARK_VIDEO_COMMAND OVERSEAARK_ASR_COMMAND OVERSEAARK_TTS_COMMAND; do
      [[ -n "${!var:-}" ]] || die "command mode requires $var"
    done
    validate_offline_runtime
    start_vllm || die "native vLLM startup failed; inspect ./overseaark logs llm"
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
  if [[ "$OVERSEAARK_ADAPTER_MODE" == "command" ]]; then
    stop_vllm
  fi
}

show_logs() {
  local target="${1:-all}"
  case "$target" in
    backend|frontend)
      touch "$OVERSEAARK_LOG_DIR/$target.log"
      exec tail -n 80 -f "$OVERSEAARK_LOG_DIR/$target.log"
      ;;
    llm)
      touch "$OVERSEAARK_LOG_DIR/llm.log"
      exec tail -n 120 -f "$OVERSEAARK_LOG_DIR/llm.log"
      ;;
    all)
      touch "$OVERSEAARK_LOG_DIR/backend.log" "$OVERSEAARK_LOG_DIR/frontend.log"
      exec tail -n 80 -f "$OVERSEAARK_LOG_DIR/backend.log" "$OVERSEAARK_LOG_DIR/frontend.log"
      ;;
    *)
      die "logs target must be backend, frontend, llm, or all" 64
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
      printf 'resident   %s\n' "$OVERSEAARK_RESIDENT_ADAPTERS"
      printf 'keep-vllm  %s\n' "$OVERSEAARK_KEEP_VLLM_RESIDENT"
      status_one backend
      if [[ "$OVERSEAARK_ADAPTER_MODE" == "command" ]]; then
        status_vllm
      fi
      if frontend_dist_ready; then
        printf '%-10s built\n' "frontend"
      elif [[ -f "$REPO_DIR/runtime/frontend-dist/index.html" ]]; then
        printf '%-10s stale-dist\n' "frontend"
      else
        printf '%-10s missing-dist\n' "frontend"
      fi
      ;;
    logs) shift || true; show_logs "${1:-all}" ;;
    llm)
      case "${2:-status}" in
        start) start_vllm ;;
        stop) stop_vllm ;;
        status) status_vllm ;;
        *) die "llm command must be start, stop, or status" 64 ;;
      esac
      ;;
    *) die "unknown lifecycle command: ${1:-}" 64 ;;
  esac
fi
