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

# Native llama.cpp command must use only locked local GGUFs and loopback API.
OVERSEAARK_LLAMA_SERVER="$tmp_dir/fake-llama/bin/llama-server"
OVERSEAARK_LLAMA_MODEL="$tmp_dir/models/qwen/Qwen3.6-Q4_K_M.gguf"
OVERSEAARK_LLAMA_MMPROJ="$tmp_dir/models/qwen/mmproj-BF16.gguf"
OVERSEAARK_LLAMA_API_KEY_FILE="$tmp_dir/data/run/llama-api-key"
OVERSEAARK_LLAMA_PORT=18011
native_command="$(llama_command)"
[[ "$native_command" == *"127.0.0.1"* ]]
[[ "$native_command" == *"--gpu-layers all"* ]]
[[ "$native_command" == *"--flash-attn on"* ]]
[[ "$native_command" == *"--mmproj"* ]]
[[ "$native_command" == *"--no-webui"* ]]
[[ "$native_command" == *"--api-key-file"* ]]
[[ "$native_command" == *"--cors-origins localhost"* ]]
[[ "$native_command" == *"HF_HUB_OFFLINE=1"* ]]
[[ "$native_command" != *"docker"* ]]

# Fault: malformed startup configuration must fail before any process action.
if (OVERSEAARK_STARTUP_TIMEOUT=invalid; validate_startup_configuration) >/dev/null 2>&1; then
  echo "malformed startup timeout unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_BACKEND_PORT=70000; validate_startup_configuration) >/dev/null 2>&1; then
  echo "out-of-range backend port unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_LLAMA_STARTUP_TIMEOUT=invalid; validate_startup_configuration) >/dev/null 2>&1; then
  echo "malformed LLM startup timeout unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_LLAMA_PORT=70000; validate_startup_configuration) >/dev/null 2>&1; then
  echo "out-of-range LLM port unexpectedly passed validation" >&2
  exit 1
fi
if (OVERSEAARK_ADAPTER_MODE=command OVERSEAARK_LLM_BASE_URL=https://example.invalid; validate_offline_runtime) >/dev/null 2>&1; then
  echo "remote LLM server URL unexpectedly passed offline runtime validation" >&2
  exit 1
fi

# Command-mode startup must launch the native llama.cpp process. Heavy dependencies
# are stubbed so this remains a no-download regression test.
: > "$STUB_STATE_DIR/native-start-calls"
ensure_runtime_dependencies() { printf 'runtime\n' >> "$STUB_STATE_DIR/native-start-calls"; }
ensure_models() { printf 'models\n' >> "$STUB_STATE_DIR/native-start-calls"; }
validate_offline_runtime() { printf 'offline\n' >> "$STUB_STATE_DIR/native-start-calls"; }
backend_cmd() { printf 'true'; }
frontend_cmd() { printf 'true'; }
start_one() { printf 'start-one:%s\n' "$1" >> "$STUB_STATE_DIR/native-start-calls"; }
wait_for_backend() { printf 'backend-ready\n' >> "$STUB_STATE_DIR/native-start-calls"; }
start_llama() {
  printf 'start-llama\n' >> "$STUB_STATE_DIR/native-start-calls"
}
OVERSEAARK_ADAPTER_MODE=command
OVERSEAARK_MOCK_MODE=0
OVERSEAARK_HOST=127.0.0.1
start_all
grep -qx 'start-llama' "$STUB_STATE_DIR/native-start-calls"
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
