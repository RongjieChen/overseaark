#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

export PIP_INDEX_URL="${PIP_INDEX_URL:-$OVERSEAARK_PYPI_INDEX}"
if [[ -n "$OVERSEAARK_GITHUB_GIT_PREFIX" ]]; then
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0="url.${OVERSEAARK_GITHUB_GIT_PREFIX}.insteadOf"
  export GIT_CONFIG_VALUE_0="https://github.com/"
fi

bootstrap_owns_lock=0
if [[ "${OVERSEAARK_OPERATION_LOCK_HELD:-0}" != "1" ]]; then
  acquire_operation_lock bootstrap
  bootstrap_owns_lock=1
  trap release_operation_lock EXIT
fi

install_system_packages() {
  if have ffmpeg && node22_available && have git && have cmake && have c++ && python_dev_headers_available; then
    return 0
  fi
  if [[ "$(uname -s)" != "Linux" ]] || ! have apt-get; then
    warn "ffmpeg/Node 22/npm/Python development headers missing and apt-get unavailable; install them manually on this host"
    return 0
  fi

  local sudo_cmd=()
  if [[ "$(id -u)" != "0" ]]; then
    have sudo || die "sudo is required to install ffmpeg/node/npm"
    sudo_cmd=(sudo)
  fi
  "${sudo_cmd[@]}" apt-get update
  "${sudo_cmd[@]}" apt-get install -y \
    build-essential ca-certificates cmake curl ffmpeg git git-lfs pkg-config \
    python3-dev python3-venv xz-utils
  install_node22 "${sudo_cmd[@]}"
}

python_dev_headers_available() {
  have python3 || return 1
  python3 - <<'PY' >/dev/null 2>&1
import pathlib
import sysconfig

include_dir = pathlib.Path(sysconfig.get_path("include"))
raise SystemExit(0 if (include_dir / "Python.h").is_file() else 1)
PY
}

node22_available() {
  have node && have npm && [[ "$(node -p 'process.versions.node.split(`.`)[0]' 2>/dev/null)" -ge 22 ]]
}

install_node22() {
  node22_available && return 0
  [[ "$(uname -m)" == "aarch64" ]] || die "automatic Node 22 install supports target aarch64 only"
  local sudo_cmd=("$@")
  local version="22.23.1"
  local archive="node-v${version}-linux-arm64.tar.xz"
  local base="https://nodejs.org/dist/v${version}"
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSLo "$tmp/$archive" "$base/$archive"
  curl -fsSLo "$tmp/SHASUMS256.txt" "$base/SHASUMS256.txt"
  (cd "$tmp" && grep " $archive\$" SHASUMS256.txt | sha256sum -c -)
  "${sudo_cmd[@]}" mkdir -p "/usr/local/lib/overseaark-node-${version}"
  "${sudo_cmd[@]}" tar -xJf "$tmp/$archive" \
    -C "/usr/local/lib/overseaark-node-${version}" --strip-components=1
  "${sudo_cmd[@]}" ln -sfn "/usr/local/lib/overseaark-node-${version}/bin/node" /usr/local/bin/node
  "${sudo_cmd[@]}" ln -sfn "/usr/local/lib/overseaark-node-${version}/bin/npm" /usr/local/bin/npm
  "${sudo_cmd[@]}" ln -sfn "/usr/local/lib/overseaark-node-${version}/bin/npx" /usr/local/bin/npx
  rm -rf "$tmp"
  node22_available || die "Node 22 installation failed"
}

create_python_env() {
  if [[ -d "$REPO_DIR/backend" ]]; then
    if [[ ! -d "$REPO_DIR/backend/.venv" ]]; then
      have python3 || die "python3 is required"
      log "creating backend Python environment backend/.venv"
      python3 -m venv "$REPO_DIR/backend/.venv"
    fi

    local python="$REPO_DIR/backend/.venv/bin/python"
    if (cd "$REPO_DIR/backend" && \
      "$python" -c 'import app, fastapi, multipart, pydantic, uvicorn' 2>/dev/null); then
      log "backend Python dependencies already available"
      return 0
    fi

    local pip="$REPO_DIR/backend/.venv/bin/pip"
    [[ -x "$pip" ]] || die "backend/.venv is incomplete; recreate it with python3 -m venv backend/.venv"
    if [[ -f "$REPO_DIR/backend/pyproject.toml" ]]; then
      "$pip" install --upgrade pip wheel setuptools
      "$pip" install -e "$REPO_DIR/backend"
    elif [[ -f "$REPO_DIR/backend/requirements.txt" ]]; then
      "$pip" install --upgrade pip wheel setuptools
      "$pip" install -r "$REPO_DIR/backend/requirements.txt"
    else
      "$pip" install --upgrade pip wheel setuptools
      "$pip" install fastapi uvicorn
    fi
  else
    warn "backend/ not present; skipping Python app dependency install"
  fi
}

rewrite_cosmos_locked_urls() {
  local lock_file="$REPO_DIR/vendor/cosmos-framework/uv.lock"
  [[ -f "$lock_file" ]] || die "Cosmos uv.lock is missing: $lock_file"
  python3 - "$lock_file" "$1" \
    "$OVERSEAARK_PYPI_FILE_PREFIX" "$OVERSEAARK_GITHUB_ASSET_PREFIX" <<'PY'
import subprocess
import sys
from pathlib import Path

path = Path(sys.argv[1])
revision = sys.argv[2]
pypi_prefix = sys.argv[3].rstrip("/") + "/" if sys.argv[3] else ""
github_prefix = sys.argv[4].rstrip("/") + "/" if sys.argv[4] else ""
canonical = subprocess.run(
    ["git", "-C", str(path.parent), "show", f"{revision}:uv.lock"],
    check=True,
    stdout=subprocess.PIPE,
    text=True,
).stdout
pypi_marker = "https://files.pythonhosted.org/"
github_marker = "https://github.com/nvidia-cosmos/cosmos-dependencies/releases/download/"
rewritten = []
for line in canonical.splitlines(keepends=True):
    marker = github_marker if github_marker in line else pypi_marker if pypi_marker in line else ""
    prefix = github_prefix if marker == github_marker else pypi_prefix
    marker_at = line.find(marker) if marker and prefix else -1
    if marker_at >= 0 and line.lstrip().startswith("{ url = \""):
        url_start = line.find("https://")
        url_end = line.find('"', marker_at)
        suffix = line[marker_at:url_end] if marker == github_marker else line[marker_at + len(marker):url_end]
        line = line[:url_start] + prefix + suffix + line[url_end:]
    rewritten.append(line)
path.write_text("".join(rewritten), encoding="utf-8")
PY
}

prepare_open_jtalk_dictionary() {
  local python="$REPO_DIR/.venv-tts/bin/python"
  local package_dir target_dir tmp archive url
  package_dir="$("$python" -c 'import pathlib, pyopenjtalk; print(pathlib.Path(pyopenjtalk.__file__).parent)')"
  target_dir="$package_dir/open_jtalk_dic_utf_8-1.11"
  [[ -f "$target_dir/sys.dic" ]] && return 0

  tmp="$(mktemp -d /tmp/overseaark-open-jtalk.XXXXXX)"
  archive="$tmp/open_jtalk_dic_utf_8-1.11.tar.gz"
  url="${OVERSEAARK_GITHUB_ASSET_PREFIX}https://github.com/r9y9/open_jtalk/releases/download/v1.11.1/open_jtalk_dic_utf_8-1.11.tar.gz"
  curl -fL --retry 5 --retry-delay 2 -o "$archive" "$url"
  printf '%s  %s\n' \
    "fe6ba0e43542cef98339abdffd903e062008ea170b04e7e2a35da805902f382a" \
    "$archive" | sha256sum -c -
  tar -xzf "$archive" --no-same-owner -C "$package_dir"
  rm -f "$archive"
  rmdir "$tmp"
  [[ -f "$target_dir/sys.dic" ]] || die "Open JTalk dictionary extraction failed"
}

install_frontend() {
  if [[ -f "$REPO_DIR/frontend/package.json" ]]; then
    if [[ -f "$REPO_DIR/frontend/package-lock.json" ]]; then
      local npm
      npm="$(npm_bin)" || die "npm is required for frontend/package-lock.json"
      (cd "$REPO_DIR/frontend" && "$npm" ci && "$npm" run build)
    elif have pnpm && [[ -f "$REPO_DIR/frontend/pnpm-lock.yaml" ]]; then
      (cd "$REPO_DIR/frontend" && pnpm install --frozen-lockfile && pnpm run build)
    else
      local npm
      npm="$(npm_bin)" || die "npm is required for frontend/package.json"
      (cd "$REPO_DIR/frontend" && "$npm" install && "$npm" run build)
    fi
    [[ -f "$REPO_DIR/runtime/frontend-dist/index.html" ]] || die "frontend build did not create runtime/frontend-dist/index.html"
  else
    warn "frontend/package.json not present; skipping frontend install/build"
  fi
}

create_adapter_envs() {
  if is_truthy "$OVERSEAARK_MOCK_MODE"; then
    warn "OVERSEAARK_MOCK_MODE=1; skipping heavy adapter env installation"
    return 0
  fi
  have python3 || die "python3 is required"
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' || \
    die "heavy adapter environments require Python 3.12"

  if [[ ! -d "$REPO_DIR/.venv-step1x" ]]; then
    python3 -m venv "$REPO_DIR/.venv-step1x"
  fi
  "$REPO_DIR/.venv-step1x/bin/pip" install --upgrade pip wheel setuptools
  "$REPO_DIR/.venv-step1x/bin/pip" install \
    filelock "typing-extensions>=4.10" "sympy>=1.13.3" \
    "networkx>=2.5.1" jinja2 "fsspec>=0.8.5" pillow numpy
  "$REPO_DIR/.venv-step1x/bin/pip" install --extra-index-url https://download.pytorch.org/whl/cu130 torch torchvision
  "$REPO_DIR/.venv-step1x/bin/pip" install \
    "transformers==4.55.0" "megfile==5.0.14" "qwen-vl-utils==0.0.14" \
    pillow accelerate sentencepiece protobuf
  local step1x_diffusers_revision="f5f1c98fa00cb4d0479af1b1b1c17d724345963a"
  if [[ ! -d "$REPO_DIR/vendor/diffusers-step1xedit_v1p2/.git" ]]; then
    mkdir -p "$REPO_DIR/vendor"
    git clone --branch step1xedit_v1p2 --depth 1 https://github.com/Peyton-Chen/diffusers.git "$REPO_DIR/vendor/diffusers-step1xedit_v1p2"
  fi
  if ! git -C "$REPO_DIR/vendor/diffusers-step1xedit_v1p2" cat-file -e "${step1x_diffusers_revision}^{commit}"; then
    git -C "$REPO_DIR/vendor/diffusers-step1xedit_v1p2" fetch --depth 1 origin "$step1x_diffusers_revision"
  fi
  git -C "$REPO_DIR/vendor/diffusers-step1xedit_v1p2" checkout --detach "$step1x_diffusers_revision"
  "$REPO_DIR/.venv-step1x/bin/pip" install -e "$REPO_DIR/vendor/diffusers-step1xedit_v1p2"

  if [[ ! -d "$REPO_DIR/.venv-cosmos" ]]; then
    python3 -m venv "$REPO_DIR/.venv-cosmos"
  fi
  "$REPO_DIR/.venv-cosmos/bin/pip" install --upgrade pip wheel setuptools uv
  local cosmos_framework_revision="ed8287fd7477113f8ac4f6b84290514d55cf0cdc"
  if [[ ! -d "$REPO_DIR/vendor/cosmos-framework/.git" ]]; then
    mkdir -p "$REPO_DIR/vendor"
    git clone https://github.com/NVIDIA/cosmos-framework.git "$REPO_DIR/vendor/cosmos-framework"
  fi
  if ! git -C "$REPO_DIR/vendor/cosmos-framework" cat-file -e "${cosmos_framework_revision}^{commit}"; then
    git -C "$REPO_DIR/vendor/cosmos-framework" fetch --depth 1 origin "$cosmos_framework_revision"
  fi
  git -C "$REPO_DIR/vendor/cosmos-framework" checkout --detach "$cosmos_framework_revision"
  rewrite_cosmos_locked_urls "$cosmos_framework_revision"
  (
    cd "$REPO_DIR/vendor/cosmos-framework"
    UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-$OVERSEAARK_PYPI_INDEX}" \
      UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}" \
      UV_HTTP_RETRIES="${UV_HTTP_RETRIES:-10}" \
      UV_CONCURRENT_DOWNLOADS="${UV_CONCURRENT_DOWNLOADS:-4}" \
      "$REPO_DIR/.venv-cosmos/bin/uv" sync --frozen --group=cu130
  )
  # The pinned framework imports iopath from its inference entrypoint but lists
  # it only under the much larger training extra.
  "$REPO_DIR/.venv-cosmos/bin/uv" pip install \
    --python "$REPO_DIR/vendor/cosmos-framework/.venv/bin/python" \
    --index-url "$OVERSEAARK_PYPI_INDEX" "iopath==0.1.10"

  # Nemotron 3.5 ASR targets NeMo 26.06/main while Magpie v2602 targets
  # the stable 25.11-era API. Keep their dependency graphs isolated.
  if [[ ! -d "$REPO_DIR/.venv-asr" ]]; then
    python3 -m venv "$REPO_DIR/.venv-asr"
  fi
  "$REPO_DIR/.venv-asr/bin/pip" install --upgrade pip wheel setuptools Cython packaging
  "$REPO_DIR/.venv-asr/bin/pip" install \
    filelock "typing-extensions>=4.10" "sympy>=1.13.3" \
    "networkx>=2.5.1" jinja2 "fsspec>=0.8.5" numpy
  "$REPO_DIR/.venv-asr/bin/pip" install --extra-index-url https://download.pytorch.org/whl/cu130 torch torchaudio
  "$REPO_DIR/.venv-asr/bin/pip" install \
    "nemo_toolkit[asr] @ git+https://github.com/NVIDIA-NeMo/NeMo.git@93b15b1f423ddc8e0d189810fdd8304091d9b1bd" \
    kaldialign soundfile

  if [[ ! -d "$REPO_DIR/.venv-tts" ]]; then
    python3 -m venv "$REPO_DIR/.venv-tts"
  fi
  "$REPO_DIR/.venv-tts/bin/pip" install --upgrade pip wheel setuptools Cython packaging
  "$REPO_DIR/.venv-tts/bin/pip" install \
    filelock "typing-extensions>=4.10" "sympy>=1.13.3" \
    "networkx>=2.5.1" jinja2 numpy
  "$REPO_DIR/.venv-tts/bin/pip" install --extra-index-url https://download.pytorch.org/whl/cu130 torch torchaudio
  "$REPO_DIR/.venv-tts/bin/pip" install --no-build-isolation \
    "nemo_toolkit[tts]==2.7.3" kaldialign soundfile
  prepare_open_jtalk_dictionary
}

ensure_dirs

if is_truthy "$OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP"; then
  install_system_packages
  create_python_env
  install_frontend
  if ! is_truthy "$OVERSEAARK_MOCK_MODE"; then
    bash "$SCRIPT_DIR/llama_server.sh" install
  fi
  create_adapter_envs
else
  warn "OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP=0; skipping dependency installation"
fi

if is_truthy "$OVERSEAARK_SKIP_MODELS"; then
  warn "OVERSEAARK_SKIP_MODELS=1; skipping model sync"
else
  OVERSEAARK_OPERATION_LOCK_HELD=1 bash "$SCRIPT_DIR/models.sh" sync
fi

if (( bootstrap_owns_lock == 1 )); then
  release_operation_lock
  trap - EXIT
fi
log "bootstrap complete"
