#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

failures=0

run() {
  local name="$1"
  shift
  printf '[test] %s\n' "$name"
  if "$@"; then
    printf '[pass] %s\n' "$name"
  else
    printf '[fail] %s\n' "$name"
    failures=$((failures + 1))
  fi
}

run_shell() {
  local name="$1"
  shift
  run "$name" bash -lc "$*"
}

backend_tests() {
  if [[ ! -d "$REPO_DIR/backend/tests" ]]; then
    warn "backend/tests not present; skipping backend tests"
    return 0
  fi
  if [[ ! -x "$REPO_DIR/backend/.venv/bin/python" ]]; then
    have python3 || die "python3 is required for backend tests"
    python3 -m venv "$REPO_DIR/backend/.venv"
  fi
  if ! (cd "$REPO_DIR/backend" && \
    "$REPO_DIR/backend/.venv/bin/python" -c 'import app, httpx, pytest'); then
    "$REPO_DIR/backend/.venv/bin/python" -m pip install \
      --quiet --break-system-packages -e "$REPO_DIR/backend[test]"
  fi
  (cd "$REPO_DIR/backend" && "$REPO_DIR/backend/.venv/bin/python" -m pytest)
}

frontend_tests() {
  if [[ ! -f "$REPO_DIR/frontend/package.json" ]]; then
    warn "frontend/package.json not present; skipping frontend tests"
    return 0
  fi
  if have npm && [[ -f "$REPO_DIR/frontend/package-lock.json" ]]; then
    (cd "$REPO_DIR/frontend" && npm run test && npm run build)
  elif have pnpm && [[ -f "$REPO_DIR/frontend/pnpm-lock.yaml" ]]; then
    (cd "$REPO_DIR/frontend" && pnpm run test && pnpm run build)
  elif have npm && [[ -d "$REPO_DIR/frontend/node_modules" ]]; then
    (cd "$REPO_DIR/frontend" && npm run test && npm run build)
  else
    warn "frontend dependencies missing; skipping frontend npm tests/build"
    return 0
  fi
}

e2e_tests() {
  if [[ ! -d "$REPO_DIR/tests/e2e" ]]; then
    warn "tests/e2e not present; skipping e2e tests"
    return 0
  fi
  if [[ -f "$REPO_DIR/tests/e2e/run_e2e.py" ]]; then
    /usr/bin/python3 "$REPO_DIR/tests/e2e/run_e2e.py" --mock
    return $?
  fi
  if find "$REPO_DIR/tests/e2e" -type f ! -name '.keep' | grep -q .; then
    warn "tests/e2e contains specs but no known runner"
    return 1
  fi
  warn "tests/e2e has no runnable specs yet"
  return 0
}

health_smoke() {
  OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 OVERSEAARK_ADAPTER_MODE=mock bash "$REPO_DIR/overseaark" start
  trap 'OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 bash "$REPO_DIR/overseaark" stop >/dev/null 2>&1 || true' RETURN
  if have curl; then
    curl -fsS --retry 10 --retry-connrefused --retry-delay 1 --max-time 2 "http://${OVERSEAARK_HOST}:${OVERSEAARK_BACKEND_PORT}/health" >/dev/null
  else
    local pid
    pid="$(read_pid backend || true)"
    pid_alive "$pid"
  fi
}

run "dispatcher help" bash "$REPO_DIR/overseaark" help
run "status" bash "$REPO_DIR/overseaark" status
OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 run "doctor mock" bash "$REPO_DIR/overseaark" doctor
OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 run "models verify relaxed" bash "$REPO_DIR/overseaark" models verify
run "backend tests" backend_tests
run "frontend tests/build" frontend_tests
run "one-click adversarial lifecycle" bash "$REPO_DIR/tests/e2e/test_oneclick_start.sh"
run "backend health smoke" health_smoke
run "tests/e2e" e2e_tests

if (( failures > 0 )); then
  die "$failures smoke test(s) failed"
fi

log "smoke tests passed"
