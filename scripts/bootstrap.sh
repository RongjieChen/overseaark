#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

install_system_packages() {
  if have ffmpeg && node22_available; then
    return 0
  fi
  if [[ "$(uname -s)" != "Linux" ]] || ! have apt-get; then
    warn "ffmpeg/Node 22/npm missing and apt-get unavailable; install them manually on this host"
    return 0
  fi

  local sudo_cmd=()
  if [[ "$(id -u)" != "0" ]]; then
    have sudo || die "sudo is required to install ffmpeg/node/npm"
    sudo_cmd=(sudo)
  fi
  "${sudo_cmd[@]}" apt-get update
  "${sudo_cmd[@]}" apt-get install -y ca-certificates curl ffmpeg git-lfs xz-utils
  install_node22 "${sudo_cmd[@]}"
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
  "$REPO_DIR/.venv-step1x/bin/pip" install "transformers==4.55.0" pillow accelerate sentencepiece protobuf
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
  (
    cd "$REPO_DIR/vendor/cosmos-framework"
    UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}" \
      UV_HTTP_RETRIES="${UV_HTTP_RETRIES:-10}" \
      "$REPO_DIR/.venv-cosmos/bin/uv" sync --group=cu130
  )

  if [[ ! -d "$REPO_DIR/.venv-nemo" ]]; then
    python3 -m venv "$REPO_DIR/.venv-nemo"
  fi
  "$REPO_DIR/.venv-nemo/bin/pip" install --upgrade pip wheel setuptools
  "$REPO_DIR/.venv-nemo/bin/pip" install \
    filelock "typing-extensions>=4.10" "sympy>=1.13.3" \
    "networkx>=2.5.1" jinja2 "fsspec>=0.8.5" numpy
  "$REPO_DIR/.venv-nemo/bin/pip" install --extra-index-url https://download.pytorch.org/whl/cu130 torch torchaudio
  "$REPO_DIR/.venv-nemo/bin/pip" install \
    "nemo_toolkit[asr,tts] @ git+https://github.com/NVIDIA-NeMo/NeMo.git@93b15b1f423ddc8e0d189810fdd8304091d9b1bd" \
    kaldialign soundfile
}

ensure_dirs

if is_truthy "$OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP"; then
  install_system_packages
  create_python_env
  install_frontend
  create_adapter_envs
else
  warn "OVERSEAARK_ENABLE_NETWORK_BOOTSTRAP=0; skipping dependency installation"
fi

if is_truthy "$OVERSEAARK_SKIP_MODELS"; then
  warn "OVERSEAARK_SKIP_MODELS=1; skipping model sync"
else
  bash "$SCRIPT_DIR/models.sh" sync
fi

log "bootstrap complete"
