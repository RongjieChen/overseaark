#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp_dir="$(mktemp -d)"
cleanup_pids=()
cleanup() {
  local cleanup_pid
  for cleanup_pid in "${cleanup_pids[@]}"; do
    if [[ "$cleanup_pid" =~ ^[1-9][0-9]*$ ]]; then
      kill -KILL "$cleanup_pid" >/dev/null 2>&1 || true
    fi
  done
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

export OVERSEAARK_DATA_DIR="$tmp_dir/data"
export OVERSEAARK_MODELS_DIR="$tmp_dir/models"
export OVERSEAARK_LOG_DIR="$tmp_dir/data/logs"
export OVERSEAARK_PID_DIR="$tmp_dir/data/run"
export OVERSEAARK_MOCK_MODE=0
export OVERSEAARK_SKIP_MODELS=0
export OVERSEAARK_AUTO_BOOTSTRAP=1
export OVERSEAARK_AUTO_DOWNLOAD_MODELS=1
export OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP=1
export STUB_STATE_DIR="$tmp_dir/state"
mkdir -p "$STUB_STATE_DIR"

stub_models="$tmp_dir/models-stub.sh"
cat > "$stub_models" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$1" >> "$STUB_STATE_DIR/model-calls"
case "$1" in
  verify) [[ -f "$STUB_STATE_DIR/models-valid" ]] ;;
  sync) touch "$STUB_STATE_DIR/models-valid" ;;
  *) exit 64 ;;
esac
SH
chmod +x "$stub_models"

stub_bootstrap="$tmp_dir/bootstrap-stub.sh"
cat > "$stub_bootstrap" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'bootstrap\n' >> "$STUB_STATE_DIR/bootstrap-calls"
touch "$STUB_STATE_DIR/runtime-valid"
SH
chmod +x "$stub_bootstrap"

export OVERSEAARK_MODELS_SCRIPT="$stub_models"
export OVERSEAARK_BOOTSTRAP_SCRIPT="$stub_bootstrap"
# shellcheck disable=SC1091
source "$repo_dir/scripts/lifecycle.sh"

# Fault: missing or corrupt locked model. Expect verify -> sync and a usable result.
ensure_models
[[ "$(sed -n '1p' "$STUB_STATE_DIR/model-calls")" == "verify" ]]
[[ "$(sed -n '2p' "$STUB_STATE_DIR/model-calls")" == "sync" ]]
[[ -f "$STUB_STATE_DIR/models-valid" ]]

# Idempotence: a second preflight verifies but does not download again.
ensure_models
[[ "$(grep -c '^sync$' "$STUB_STATE_DIR/model-calls")" == "1" ]]

# Fault: a source update must invalidate an existing frontend dist, rebuild only
# the frontend once, and leave the heavy bootstrap untouched. A fresh dist is
# then idempotent.
frontend_fixture="$tmp_dir/frontend-fixture"
mkdir -p "$frontend_fixture/frontend/src" "$frontend_fixture/frontend/public/demo" \
  "$frontend_fixture/runtime/frontend-dist/demo"
printf '<html lang="zh-CN">new source</html>\n' > "$frontend_fixture/frontend/index.html"
printf 'console.log("new source");\n' > "$frontend_fixture/frontend/src/main.ts"
printf '<html lang="en">old dist</html>\n' > "$frontend_fixture/runtime/frontend-dist/index.html"
printf 'same demo bytes\n' > "$frontend_fixture/frontend/public/demo/portable-smart-espresso-maker.png"
cp "$frontend_fixture/frontend/public/demo/portable-smart-espresso-maker.png" \
  "$frontend_fixture/runtime/frontend-dist/demo/portable-smart-espresso-maker.png"
touch -t 202001010000 "$frontend_fixture/runtime/frontend-dist/index.html"
touch -t 202001010001 "$frontend_fixture/frontend/index.html" "$frontend_fixture/frontend/src/main.ts"

(
  export FRONTEND_FIXTURE="$frontend_fixture"
  REPO_DIR="$frontend_fixture"
  OVERSEAARK_ADAPTER_MODE=mock
  frontend_build_dependencies_ready() { return 0; }
  build_frontend_assets() {
    printf 'frontend-build\n' >> "$STUB_STATE_DIR/frontend-build-calls"
    cp "$FRONTEND_FIXTURE/frontend/index.html" "$FRONTEND_FIXTURE/runtime/frontend-dist/index.html"
    touch "$FRONTEND_FIXTURE/runtime/frontend-dist/index.html"
  }
  if frontend_dist_ready; then
    echo "stale frontend dist unexpectedly passed freshness check" >&2
    exit 1
  fi
  runtime_dependencies_ready
  ensure_frontend_assets
  ensure_frontend_assets
)
[[ "$(grep -c '^frontend-build$' "$STUB_STATE_DIR/frontend-build-calls")" == "1" ]]
[[ ! -e "$STUB_STATE_DIR/frontend-bootstrap-calls" ]]

# Fault: ffmpeg is a backend upload-validation dependency in mock and command
# modes, so mock preflight must not report ready when it is absent.
(
  REPO_DIR="$frontend_fixture"
  OVERSEAARK_ADAPTER_MODE=mock
  have() { [[ "$1" != "ffmpeg" ]]; }
  if runtime_dependencies_ready; then
    echo "mock runtime unexpectedly passed without ffmpeg" >&2
    exit 1
  fi
)

# Fault: a public asset update must invalidate the built frontend even when
# source code and configuration are older than the dist index.
public_fixture="$tmp_dir/frontend-public-fixture"
mkdir -p "$public_fixture/frontend/public/demo" "$public_fixture/runtime/frontend-dist/demo"
printf '<html>fresh dist</html>\n' > "$public_fixture/runtime/frontend-dist/index.html"
printf 'new demo image bytes\n' > "$public_fixture/frontend/public/demo/portable-smart-espresso-maker.png"
printf 'old demo image bytes\n' > "$public_fixture/runtime/frontend-dist/demo/portable-smart-espresso-maker.png"
touch -t 202001010000 "$public_fixture/runtime/frontend-dist/index.html"
touch -t 202001010001 "$public_fixture/frontend/public/demo/portable-smart-espresso-maker.png"
(
  REPO_DIR="$public_fixture"
  if frontend_dist_ready; then
    echo "updated frontend/public asset unexpectedly passed freshness check" >&2
    exit 1
  fi
)

# Fault: deleting the required source asset must not leave a stale bundled copy
# reported as ready.
rm -f "$public_fixture/frontend/public/demo/portable-smart-espresso-maker.png"
(
  REPO_DIR="$public_fixture"
  if frontend_dist_ready; then
    echo "deleted required demo source unexpectedly passed freshness check" >&2
    exit 1
  fi
)

# Fault: the documented TUNA file prefix already ends in /packages/. Cosmos
# lock rewriting must not generate an invalid /packages/packages/ URL.
cosmos_fixture="$tmp_dir/cosmos-rewrite-repo"
mkdir -p "$cosmos_fixture/vendor/cosmos-framework"
cat > "$cosmos_fixture/vendor/cosmos-framework/uv.lock" <<'LOCK'
wheels = [
  { url = "https://files.pythonhosted.org/packages/46/10/example.whl", hash = "sha256:example", size = 1 },
]
LOCK
git -C "$cosmos_fixture/vendor/cosmos-framework" init -q
git -C "$cosmos_fixture/vendor/cosmos-framework" config user.email test@overseaark.local
git -C "$cosmos_fixture/vendor/cosmos-framework" config user.name OverseaArk-Test
git -C "$cosmos_fixture/vendor/cosmos-framework" add uv.lock
git -C "$cosmos_fixture/vendor/cosmos-framework" commit -qm fixture
(
  REPO_DIR="$cosmos_fixture"
  OVERSEAARK_PYPI_FILE_PREFIX="https://pypi.tuna.tsinghua.edu.cn/packages/"
  OVERSEAARK_GITHUB_ASSET_PREFIX=""
  # Load only the production rewrite function; bootstrap.sh intentionally runs
  # installation work when sourced as a whole.
  # shellcheck disable=SC1090
  source /dev/stdin <<< "$(sed -n '/^rewrite_cosmos_locked_urls()/,/^}/p' "$repo_dir/scripts/bootstrap.sh")"
  rewrite_cosmos_locked_urls HEAD
)
grep -q 'https://pypi.tuna.tsinghua.edu.cn/packages/46/10/example.whl' \
  "$cosmos_fixture/vendor/cosmos-framework/uv.lock"
if grep -q '/packages/packages/' "$cosmos_fixture/vendor/cosmos-framework/uv.lock"; then
  echo "Cosmos lock rewrite duplicated the TUNA packages path" >&2
  exit 1
fi

# Fault: runtime dependencies absent. Expect exactly one resumable bootstrap.
runtime_dependencies_ready() { [[ -f "$STUB_STATE_DIR/runtime-valid" ]]; }
ensure_runtime_dependencies
[[ "$(grep -c '^bootstrap$' "$STUB_STATE_DIR/bootstrap-calls")" == "1" ]]
ensure_runtime_dependencies
[[ "$(grep -c '^bootstrap$' "$STUB_STATE_DIR/bootstrap-calls")" == "1" ]]

# Adversarial policy: fail closed when automatic repair is explicitly disabled.
rm -f "$STUB_STATE_DIR/models-valid"
if (OVERSEAARK_AUTO_DOWNLOAD_MODELS=0; ensure_models) >/dev/null 2>&1; then
  echo "model preflight unexpectedly succeeded with repair disabled" >&2
  exit 1
fi

rm -f "$STUB_STATE_DIR/runtime-valid"
if (OVERSEAARK_AUTO_BOOTSTRAP=0; ensure_runtime_dependencies) >/dev/null 2>&1; then
  echo "dependency preflight unexpectedly succeeded with bootstrap disabled" >&2
  exit 1
fi

# Fault: a same-size file with the wrong hash must not be treated as complete.
fake_model_root="$tmp_dir/hash-models"
mkdir -p "$fake_model_root/example"
printf 'wxyz' > "$fake_model_root/example/model.bin"
fake_manifest="$tmp_dir/model-manifest.json"
cat > "$fake_manifest" <<'JSON'
{
  "models": [{
    "id": "same-size-corruption",
    "provider": "huggingface",
    "source": "unused/example",
    "revision": "pinned",
    "local_dir": "example",
    "required": true,
    "files": [{
      "path": "model.bin",
      "size": 4,
      "sha256": "770e607624d689265ca6c44884d0807d9b054d23c473c106c72be9de08b7376c"
    }]
  }]
}
JSON
export OVERSEAARK_MODEL_MANIFEST="$fake_manifest"
# shellcheck disable=SC1091
source "$repo_dir/scripts/models.sh"
if model_files_complete same-size-corruption "$fake_model_root/example"; then
  echo "same-size corrupt model unexpectedly passed locked hash validation" >&2
  exit 1
fi
remove_invalid_model_files same-size-corruption "$fake_model_root/example"
[[ ! -e "$fake_model_root/example/model.bin" ]]
printf 'good' > "$fake_model_root/example/model.bin"
OVERSEAARK_MODELS_DIR="$fake_model_root" verify_models >/dev/null

# Fault: even an overridden manifest must never delete outside its model root.
printf 'good' > "$tmp_dir/victim.bin"
unsafe_manifest="$tmp_dir/unsafe-model-manifest.json"
cat > "$unsafe_manifest" <<'JSON'
{
  "models": [{
    "id": "path-traversal",
    "provider": "huggingface",
    "source": "unused/example",
    "revision": "pinned",
    "local_dir": "example",
    "required": true,
    "files": [{
      "path": "../../victim.bin",
      "size": 4,
      "sha256": "770e607624d689265ca6c44884d0807d9b054d23c473c106c72be9de08b7376c"
    }]
  }]
}
JSON
manifest="$unsafe_manifest"
if model_files_complete path-traversal "$fake_model_root/example"; then
  echo "unsafe model path unexpectedly passed completeness check" >&2
  exit 1
fi
if (OVERSEAARK_MODELS_DIR="$fake_model_root"; verify_models) >/dev/null 2>&1; then
  echo "unsafe model path unexpectedly passed manifest verification" >&2
  exit 1
fi
if remove_invalid_model_files path-traversal "$fake_model_root/example" >/dev/null 2>&1; then
  echo "unsafe model manifest path unexpectedly passed cleanup" >&2
  exit 1
fi
[[ -f "$tmp_dir/victim.bin" ]]

# Native vLLM command must use only the locked local NVFP4 model and loopback API.
OVERSEAARK_VLLM_BIN="$tmp_dir/fake-vllm/bin/vllm"
OVERSEAARK_VLLM_MODEL_DIR="$tmp_dir/models/nvidia/qwen3.6-35b-a3b-nvfp4"
OVERSEAARK_VLLM_SERVED_MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
OVERSEAARK_VLLM_API_KEY_FILE="$tmp_dir/data/run/vllm-api-key"
OVERSEAARK_VLLM_PORT=18011
mkdir -p "$(dirname "$OVERSEAARK_VLLM_API_KEY_FILE")"
printf 'local-test-key\n' > "$OVERSEAARK_VLLM_API_KEY_FILE"
native_command="$(vllm_command)"
[[ "$native_command" == *"127.0.0.1"* ]]
[[ "$native_command" == *"VLLM_API_KEY=local-test-key"* ]]
[[ "$native_command" == *"PATH="*"fake-vllm/bin"* ]]
[[ "$native_command" == *"CUDA_HOME=/usr/local/cuda"* ]]
[[ "$native_command" == *"TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas"* ]]
[[ "$native_command" == *"serve"* ]]
[[ "$native_command" == *"nvidia/qwen3.6-35b-a3b-nvfp4"* ]]
[[ "$native_command" == *"--served-model-name nvidia/Qwen3.6-35B-A3B-NVFP4"* ]]
[[ "$native_command" == *"--tensor-parallel-size 1"* ]]
[[ "$native_command" == *"--kv-cache-dtype fp8"* ]]
[[ "$native_command" == *"--attention-backend flashinfer"* ]]
[[ "$native_command" == *"--moe-backend marlin"* ]]
[[ "$native_command" == *"--gpu-memory-utilization"* ]]
[[ "$native_command" == *"--max-model-len"* ]]
[[ "$native_command" == *"--max-num-seqs"* ]]
[[ "$native_command" == *"--max-num-batched-tokens"* ]]
[[ "$native_command" == *"--enable-chunked-prefill"* ]]
[[ "$native_command" == *"--async-scheduling"* ]]
[[ "$native_command" == *"--enable-prefix-caching"* ]]
# Bash versions render printf %q with different quote/backslash styles. Verify
# the ordered speculative config fields without depending on that rendering.
[[ "$native_command" == *method*mtp*num_speculative_tokens* ]]
[[ "$native_command" == *"--load-format fastsafetensors"* ]]
[[ "$native_command" == *"--reasoning-parser qwen3"* ]]
[[ "$native_command" == *"--tool-call-parser qwen3_xml"* ]]
[[ "$native_command" == *"--enable-auto-tool-choice"* ]]
[[ "$native_command" == *"HF_HUB_OFFLINE=1"* ]]
[[ "$native_command" == *"TRANSFORMERS_OFFLINE=1"* ]]
[[ "$native_command" != *"docker"* ]]
[[ "$native_command" != *"llama"* ]]

# Dynamic lifecycle regression: the service launches a resident-style worker
# with start_new_session=True. stop_one must terminate both the parent and that
# separately-grouped child while leaving an unrelated process in the caller's
# group untouched. Linux additionally verifies the persisted setsid PGID.
tree_fixture="$tmp_dir/process-tree.py"
tree_child_pid_file="$tmp_dir/process-tree-child.pid"
cat > "$tree_fixture" <<'PY'
import pathlib
import signal
import subprocess
import sys
import time


child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
    ],
    start_new_session=True,
)
pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")


signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    time.sleep(1)
PY

sleep 60 &
unrelated_pid="$!"
cleanup_pids+=("$unrelated_pid")
printf -v tree_command '%q %q %q' "$(command -v python3)" "$tree_fixture" "$tree_child_pid_file"
start_one process-tree "$tree_command" "$tmp_dir"
tree_parent_pid="$(read_pid process-tree)"
cleanup_pids+=("$tree_parent_pid")
tree_parent_identity="$(read_pid_identity process-tree)"
[[ -n "$tree_parent_identity" ]]
process_identity_matches "$tree_parent_pid" "$tree_parent_identity"
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  [[ -s "$tree_child_pid_file" ]] && break
  sleep 0.05
done
[[ -s "$tree_child_pid_file" ]]
tree_child_pid="$(sed -n '1p' "$tree_child_pid_file")"
cleanup_pids+=("$tree_child_pid")
pid_alive "$tree_parent_pid"
pid_alive "$tree_child_pid"
[[ "$(process_pgid "$tree_child_pid")" == "$tree_child_pid" ]]

if [[ "$(uname -s)" == "Linux" ]] && command -v setsid >/dev/null 2>&1; then
  tree_parent_pgid="$(read_pgid process-tree)"
  [[ "$tree_parent_pgid" == "$tree_parent_pid" ]]
  [[ "$(process_pgid "$tree_parent_pid")" == "$tree_parent_pgid" ]]
  [[ "$tree_parent_pgid" != "$(process_pgid "$$")" ]]
else
  [[ ! -e "$OVERSEAARK_PID_DIR/process-tree.pgid" ]]
fi

stop_one process-tree
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if ! pid_alive "$tree_parent_pid" && ! pid_alive "$tree_child_pid"; then
    break
  fi
  sleep 0.05
done
if pid_alive "$tree_parent_pid" || pid_alive "$tree_child_pid"; then
  echo "lifecycle stop left a parent or independently-sessioned child alive" >&2
  exit 1
fi
cleanup_pids=("$unrelated_pid")
pid_alive "$unrelated_pid"
[[ ! -e "$OVERSEAARK_PID_DIR/process-tree.pid" ]]
[[ ! -e "$OVERSEAARK_PID_DIR/process-tree.pgid" ]]
kill -TERM "$unrelated_pid"
wait "$unrelated_pid" 2>/dev/null || true
cleanup_pids=()

# A stale PID that has been reused as another process-group leader must never
# widen into a signal for that unrelated group. The persisted start identity
# is intentionally corrupted to exercise the fail-closed path.
stale_pid_file="$tmp_dir/stale-group.pid"
python3 - "$stale_pid_file" <<'PY'
import pathlib
import subprocess
import sys


child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    start_new_session=True,
)
pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
PY
stale_pid="$(sed -n '1p' "$stale_pid_file")"
cleanup_pids+=("$stale_pid")
printf '%s\n%s\n' "$stale_pid" 'stale-process-identity' > "$OVERSEAARK_PID_DIR/stale.pid"
write_pgid stale "$stale_pid"
stop_one stale
pid_alive "$stale_pid"
[[ ! -e "$OVERSEAARK_PID_DIR/stale.pid" ]]
[[ ! -e "$OVERSEAARK_PID_DIR/stale.pgid" ]]

# A legacy/truncated one-line PID file is also unverified. start_one must fail
# closed instead of reporting that this unrelated process is the service.
printf '%s\n' "$stale_pid" > "$OVERSEAARK_PID_DIR/legacy.pid"
if (start_one legacy 'true' "$tmp_dir") >/dev/null 2>&1; then
  echo "start accepted a live PID without persisted process identity" >&2
  exit 1
fi
pid_alive "$stale_pid"
remove_process_state legacy

kill -TERM -- "-$stale_pid"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  pid_alive "$stale_pid" || break
  sleep 0.05
done
if pid_alive "$stale_pid"; then
  echo "stale-state safety fixture did not exit during cleanup" >&2
  exit 1
fi
cleanup_pids=()

# If a recorded session leader dies before stop while a same-PGID child stays
# alive, the group can no longer be identity-verified. Keep state and report a
# recovery failure rather than deleting the only evidence and claiming success.
dead_root_pid_file="$tmp_dir/dead-root.pid"
dead_root_child_file="$tmp_dir/dead-root-child.pid"
python3 - "$dead_root_pid_file" "$dead_root_child_file" <<'PY'
import pathlib
import subprocess
import sys


root_pid_path = pathlib.Path(sys.argv[1])
child_pid_path = pathlib.Path(sys.argv[2])
code = (
    "import pathlib,subprocess,sys; "
    "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')"
)
root = subprocess.Popen(
    [sys.executable, "-c", code, str(child_pid_path)],
    start_new_session=True,
)
root_pid_path.write_text(str(root.pid), encoding="utf-8")
root.wait()
PY
dead_root_pid="$(sed -n '1p' "$dead_root_pid_file")"
dead_root_child_pid="$(sed -n '1p' "$dead_root_child_file")"
cleanup_pids+=("$dead_root_child_pid")
[[ "$(process_pgid "$dead_root_child_pid")" == "$dead_root_pid" ]]
printf '%s\n%s\n' "$dead_root_pid" 'dead-root-identity' > "$OVERSEAARK_PID_DIR/orphan.pid"
write_pgid orphan "$dead_root_pid"
if stop_one orphan >/dev/null 2>&1; then
  echo "dead group leader with a live recorded process group was reported stopped" >&2
  exit 1
fi
[[ -e "$OVERSEAARK_PID_DIR/orphan.pid" ]]
[[ -e "$OVERSEAARK_PID_DIR/orphan.pgid" ]]
process_group_alive "$dead_root_pid"
kill -TERM -- "-$dead_root_pid"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  process_group_alive "$dead_root_pid" || break
  sleep 0.05
done
if process_group_alive "$dead_root_pid"; then
  echo "dead-root recovery fixture did not exit during cleanup" >&2
  exit 1
fi
remove_process_state orphan
cleanup_pids=()

# Fault: malformed startup configuration must fail before any process action.
if (OVERSEAARK_STARTUP_TIMEOUT=invalid; validate_startup_configuration) >/dev/null 2>&1; then
  echo "malformed startup timeout unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_BACKEND_PORT=70000; validate_startup_configuration) >/dev/null 2>&1; then
  echo "out-of-range backend port unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_VLLM_STARTUP_TIMEOUT=invalid; validate_startup_configuration) >/dev/null 2>&1; then
  echo "malformed LLM startup timeout unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_VLLM_PORT=70000; validate_startup_configuration) >/dev/null 2>&1; then
  echo "out-of-range LLM port unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_ADAPTER_MODE=command OVERSEAARK_LLM_BASE_URL=https://example.invalid; validate_offline_runtime) >/dev/null 2>&1; then
  echo "remote LLM server URL unexpectedly passed offline runtime validation" >&2
  exit 1
fi

# Command-mode startup must launch the native vLLM process. Heavy dependencies
# are stubbed so this remains a no-download regression test.
: > "$STUB_STATE_DIR/native-start-calls"
ensure_runtime_dependencies() { printf 'runtime\n' >> "$STUB_STATE_DIR/native-start-calls"; }
ensure_models() { printf 'models\n' >> "$STUB_STATE_DIR/native-start-calls"; }
validate_offline_runtime() { printf 'offline\n' >> "$STUB_STATE_DIR/native-start-calls"; }
backend_cmd() { printf 'true'; }
frontend_cmd() { printf 'true'; }
start_one() { printf 'start-one:%s\n' "$1" >> "$STUB_STATE_DIR/native-start-calls"; }
wait_for_backend() { printf 'backend-ready\n' >> "$STUB_STATE_DIR/native-start-calls"; }
start_vllm() {
  printf 'start-vllm\n' >> "$STUB_STATE_DIR/native-start-calls"
}
OVERSEAARK_ADAPTER_MODE=command
OVERSEAARK_MOCK_MODE=0
OVERSEAARK_HOST=127.0.0.1
start_all
grep -qx 'start-vllm' "$STUB_STATE_DIR/native-start-calls"
OVERSEAARK_ADAPTER_MODE=mock

# Fault: hosts without flock still need an exclusive, stale-recoverable lock.
have() {
  [[ "$1" == "flock" ]] && return 1
  command -v "$1" >/dev/null 2>&1
}
acquire_operation_lock bootstrap
if (acquire_operation_lock bootstrap) >/dev/null 2>&1; then
  echo "portable operation lock allowed a concurrent acquisition" >&2
  exit 1
fi
release_operation_lock
acquire_operation_lock bootstrap
release_operation_lock

printf '[pass] one-click adversarial lifecycle recovery\n'
