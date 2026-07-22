#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

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
mkdir -p "$frontend_fixture/frontend/src" "$frontend_fixture/runtime/frontend-dist"
printf '<html lang="zh-CN">new source</html>\n' > "$frontend_fixture/frontend/index.html"
printf 'console.log("new source");\n' > "$frontend_fixture/frontend/src/main.ts"
printf '<html lang="en">old dist</html>\n' > "$frontend_fixture/runtime/frontend-dist/index.html"
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
[[ "$native_command" == *'"method":"mtp"'* ]]
[[ "$native_command" == *"--load-format fastsafetensors"* ]]
[[ "$native_command" == *"--reasoning-parser qwen3"* ]]
[[ "$native_command" == *"--tool-call-parser qwen3_xml"* ]]
[[ "$native_command" == *"--enable-auto-tool-choice"* ]]
[[ "$native_command" == *"HF_HUB_OFFLINE=1"* ]]
[[ "$native_command" == *"TRANSFORMERS_OFFLINE=1"* ]]
[[ "$native_command" != *"docker"* ]]
[[ "$native_command" != *"llama"* ]]

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
