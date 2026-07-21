#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

manifest="${OVERSEAARK_MODEL_MANIFEST:-$REPO_DIR/model-manifest.lock.json}"

json_query() {
  local expr="$1"
  local py
  py="$(python_bin)" || die "python3 is required"
  "$py" - "$manifest" "$expr" <<'PY'
import json, sys
from pathlib import Path
path, expr = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
for model in data["models"]:
    local_dir = Path(model["local_dir"])
    if local_dir.is_absolute() or ".." in local_dir.parts:
        raise SystemExit(f"unsafe model local_dir rejected: {model['local_dir']}")
    for item in model.get("files", []):
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"unsafe model manifest path rejected: {item['path']}")
    if expr == "models":
        print("\t".join([
            model["id"],
            model["provider"],
            model["source"],
            model.get("revision", "main"),
            model["local_dir"],
            "1" if model.get("required", True) else "0",
            model.get("adopt_from") or "",
            ",".join(f["path"] for f in model.get("files", []) if f.get("required", True)),
        ]))
PY
}

env_python() {
  local name="$1"
  local packages="$2"
  local dir="$REPO_DIR/.venv-$name"
  if [[ ! -x "$dir/bin/python" ]]; then
    have python3 || die "python3 is required"
    python3 -m venv "$dir"
  fi
  "$dir/bin/python" -m pip install --quiet --upgrade pip wheel setuptools
  "$dir/bin/python" -m pip install --quiet --upgrade $packages
  printf '%s\n' "$dir/bin/python"
}

sync_modelscope() {
  local source="$1" revision="$2" dest="$3" includes="${4:-}"
  local files=() py
  if [[ -n "$includes" ]]; then
    IFS=',' read -r -a files <<< "$includes"
  fi
  py="$(env_python modelscope modelscope)"
  MODELSCOPE_ENDPOINT="${MODELSCOPE_ENDPOINT:-https://modelscope.cn}" \
    "${py%/python}/modelscope" download "$source" "${files[@]}" \
      --revision "$revision" --local-dir "$dest"
}

sync_huggingface() {
  local source="$1" revision="$2" dest="$3" includes="${4:-}"
  local files=()
  if [[ -n "$includes" ]]; then
    IFS=',' read -r -a files <<< "$includes"
  fi

  # Step1X needs its scheduler, tokenizer, and pipeline configuration in
  # addition to the weight files pinned by the verification manifest.
  if [[ "$source" == "stepfun-ai/Step1X-Edit-v1p2" ]]; then
    files=()
  fi
  if have hf; then
    HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" hf download "$source" "${files[@]}" --revision "$revision" --local-dir "$dest"
  elif have huggingface-cli; then
    HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" huggingface-cli download "$source" "${files[@]}" --revision "$revision" --local-dir "$dest" --local-dir-use-symlinks False
  else
    local py
    py="$(env_python huggingface huggingface_hub)"
    HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" "$REPO_DIR/.venv-huggingface/bin/hf" download "$source" "${files[@]}" --revision "$revision" --local-dir "$dest"
  fi
}

adopt_existing() {
  local from="$1" dest="$2"
  [[ -n "$from" && -d "$from" ]] || return 1
  mkdir -p "$(dirname "$dest")"
  if [[ -e "$dest" && ! -L "$dest" ]]; then
    warn "$dest exists; not replacing with symlink to $from"
    return 1
  fi
  ln -sfn "$from" "$dest"
  log "adopted existing model directory $from -> $dest"
  return 0
}

model_files_complete() {
  local id="$1" dest="$2"
  local py
  py="$(python_bin)" || return 1
  "$py" - "$manifest" "$id" "$dest" <<'PY'
import glob, hashlib, json, os, sys
from pathlib import Path

manifest_path, model_id, root = sys.argv[1:]
data = json.load(open(manifest_path, encoding="utf-8"))
model = next(item for item in data["models"] if item["id"] == model_id)
resolved_root = Path(root).resolve()
files = [item for item in model.get("files", []) if item.get("required", True)]
if not files:
    raise SystemExit(0 if os.path.isdir(root) and any(os.scandir(root)) else 1)
for item in files:
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(1)
    matches = glob.glob(os.path.join(root, item["path"]))
    if not matches:
        raise SystemExit(1)
    for path in matches:
        try:
            Path(path).resolve().relative_to(resolved_root)
        except ValueError:
            raise SystemExit(1)
    expected_size = item.get("size")
    if expected_size is not None and os.path.getsize(matches[0]) != int(expected_size):
        raise SystemExit(1)
    expected_hash = item.get("sha256")
    if expected_hash:
        digest = hashlib.sha256()
        with open(matches[0], "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_hash.lower():
            raise SystemExit(1)
PY
}

remove_invalid_model_files() {
  local id="$1" dest="$2"
  local py
  py="$(python_bin)" || die "python3 is required"
  "$py" - "$manifest" "$id" "$dest" <<'PY'
import glob, hashlib, json, os, sys
from pathlib import Path

manifest_path, model_id, root = sys.argv[1:]
data = json.load(open(manifest_path, encoding="utf-8"))
model = next(item for item in data["models"] if item["id"] == model_id)
resolved_root = Path(root).resolve()
invalid_paths = []
for item in model.get("files", []):
    if not item.get("required", True):
        continue
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"unsafe model manifest path rejected: {item['path']}")
    for path_value in glob.glob(os.path.join(root, item["path"])):
        path = Path(path_value)
        resolved = path.resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            raise SystemExit(f"model file escapes locked root: {path}")
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"model cleanup refuses non-regular file: {path}")
        invalid = False
        expected_size = item.get("size")
        if expected_size is not None and path.stat().st_size != int(expected_size):
            invalid = True
        expected_hash = item.get("sha256")
        if expected_hash and not invalid:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            invalid = digest.hexdigest().lower() != expected_hash.lower()
        if invalid:
            invalid_paths.append(path)
for path in invalid_paths:
    path.unlink()
    print(f"[overseaark][warn] removed invalid locked model file {path}", file=sys.stderr)
PY
}

sync_models() {
  local sync_owns_lock=0
  if [[ "${OVERSEAARK_OPERATION_LOCK_HELD:-0}" != "1" ]]; then
    acquire_operation_lock bootstrap
    sync_owns_lock=1
    trap release_operation_lock EXIT
  fi
  ensure_dirs
  if is_truthy "$OVERSEAARK_SKIP_MODELS"; then
    warn "OVERSEAARK_SKIP_MODELS=1; model sync skipped"
    if (( sync_owns_lock == 1 )); then
      release_operation_lock
      trap - EXIT
    fi
    return 0
  fi

  # `.env` deliberately enables offline inference. Model acquisition is the
  # only lifecycle operation allowed to override those guards temporarily.
  export HF_HUB_OFFLINE=0
  export TRANSFORMERS_OFFLINE=0
  export HF_DATASETS_OFFLINE=0

  while IFS=$'\t' read -r id provider source revision local_dir required adopt_from includes; do
    if [[ "$required" != "1" ]] && ! is_truthy "$OVERSEAARK_SYNC_OPTIONAL_MODELS"; then
      warn "skipping optional model $id; set OVERSEAARK_SYNC_OPTIONAL_MODELS=1 to fetch it"
      continue
    fi
    local dest="$OVERSEAARK_MODELS_DIR/$local_dir"
    adopt_existing "$adopt_from" "$dest" || mkdir -p "$dest"
    if model_files_complete "$id" "$dest"; then
      log "locked model files already complete for $id; skipping network sync"
      continue
    fi
    remove_invalid_model_files "$id" "$dest"
    log "syncing $id from $provider:$source@$revision"
    case "$provider" in
      modelscope) sync_modelscope "$source" "$revision" "$dest" "$includes" ;;
      huggingface) sync_huggingface "$source" "$revision" "$dest" "$includes" ;;
      *) die "unknown model provider: $provider" ;;
    esac
  done < <(json_query models)

  verify_models
  if (( sync_owns_lock == 1 )); then
    release_operation_lock
    trap - EXIT
  fi
}

verify_models() {
  ensure_dirs
  if is_truthy "$OVERSEAARK_SKIP_MODELS" || is_truthy "$OVERSEAARK_MOCK_MODE"; then
    warn "model verification relaxed by OVERSEAARK_SKIP_MODELS or OVERSEAARK_MOCK_MODE"
    return 0
  fi

  local py
  py="$(python_bin)" || die "python3 is required"
  "$py" - "$manifest" "$OVERSEAARK_MODELS_DIR" <<'PY'
import glob, hashlib, json, os, sys
from pathlib import Path

manifest_path, root = sys.argv[1], sys.argv[2]
data = json.load(open(manifest_path, encoding="utf-8"))
errors = []
warnings = []

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

for model in data["models"]:
    local_dir = Path(model["local_dir"])
    if local_dir.is_absolute() or ".." in local_dir.parts:
        errors.append(f"{model['id']}: unsafe local_dir {model['local_dir']}")
        continue
    local = os.path.join(root, model["local_dir"])
    if not os.path.isdir(local):
        if model.get("required", True):
            errors.append(f"{model['id']}: missing directory {local}")
        continue

    files = model.get("files", [])
    if not files:
        if os.path.isdir(local) and any(os.scandir(local)):
            continue
        if model.get("required", True):
            errors.append(f"{model['id']}: no files present in {local}")
        continue

    for item in files:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"{model['id']}: unsafe file path {item['path']}")
            continue
        pattern = os.path.join(local, item["path"])
        matches = glob.glob(pattern)
        if not matches:
            msg = f"{model['id']}: missing required file pattern {item['path']}"
            if item.get("required", True):
                errors.append(msg)
            else:
                warnings.append(msg)
            continue
        resolved_local = Path(local).resolve()
        escaped = []
        for path in matches:
            try:
                Path(path).resolve().relative_to(resolved_local)
            except ValueError:
                escaped.append(path)
        if escaped:
            errors.append(f"{model['id']}: file path escapes model root: {item['path']}")
            continue
        expected = item.get("sha256", "")
        expected_size = item.get("size")
        if expected_size is not None:
            actual_size = os.path.getsize(matches[0])
            if actual_size != int(expected_size):
                errors.append(
                    f"{model['id']}: size mismatch for {item['path']} "
                    f"(got {actual_size}, expected {expected_size})"
                )
                continue
        if not expected:
            warnings.append(f"{model['id']}: no sha256 pinned for {item['path']}")
            continue
        for path in matches:
            actual = sha256(path)
            if actual.lower() != expected.lower():
                errors.append(f"{model['id']}: sha256 mismatch for {os.path.relpath(path, local)}")

for warning in warnings:
    print(f"[overseaark][warn] {warning}", file=sys.stderr)
if errors:
    for error in errors:
        print(f"[overseaark][error] {error}", file=sys.stderr)
    sys.exit(1)
print("[overseaark] model manifest verification passed")
PY
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-verify}" in
    sync) sync_models ;;
    verify) verify_models ;;
    *) die "models command must be sync or verify" 64 ;;
  esac
fi
