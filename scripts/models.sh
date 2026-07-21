#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

manifest="$REPO_DIR/model-manifest.lock.json"

json_query() {
  local expr="$1"
  local py
  py="$(python_bin)" || die "python3 is required"
  "$py" - "$manifest" "$expr" <<'PY'
import json, sys
path, expr = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
for model in data["models"]:
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
  local py
  py="$(env_python modelscope modelscope)"
  "$py" -m modelscope download --model "$source" --revision "$revision" --local_dir "$dest"
}

sync_huggingface() {
  local source="$1" revision="$2" dest="$3" includes="${4:-}"
  local files=()
  if [[ -n "$includes" ]]; then
    IFS=',' read -r -a files <<< "$includes"
  fi

  # The Step GGUF shard is large enough that an expiring Xet URL can fail near
  # completion. Keep a normal file beside the destination so curl can resume it
  # across fresh signed redirects instead of losing an opaque client cache.
  if [[ "$source" == "stepfun-ai/Step-3.7-Flash-GGUF" ]]; then
    local endpoint="${HF_ENDPOINT:-https://hf-mirror.com}"
    local file target partial url
    for file in "${files[@]}"; do
      target="$dest/$file"
      partial="${target}.overseaark-download"
      if [[ -f "$target" ]]; then
        log "using existing Hugging Face file $target"
        continue
      fi
      mkdir -p "$(dirname "$target")"
      url="${endpoint%/}/${source}/resolve/${revision}/${file}?download=true"
      log "downloading resumable Hugging Face file $file"
      curl --fail --location --continue-at - \
        --retry 100 --retry-all-errors --retry-delay 5 \
        --connect-timeout 20 --speed-time 120 --speed-limit 1024 \
        --output "$partial" "$url"
      mv "$partial" "$target"
    done
    return 0
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

sync_models() {
  ensure_dirs
  if is_truthy "$OVERSEAARK_SKIP_MODELS"; then
    warn "OVERSEAARK_SKIP_MODELS=1; model sync skipped"
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
    log "syncing $id from $provider:$source@$revision"
    case "$provider" in
      modelscope) sync_modelscope "$source" "$revision" "$dest" "$includes" ;;
      huggingface) sync_huggingface "$source" "$revision" "$dest" "$includes" ;;
      *) die "unknown model provider: $provider" ;;
    esac
  done < <(json_query models)

  verify_models
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
        pattern = os.path.join(local, item["path"])
        matches = glob.glob(pattern)
        if not matches:
            msg = f"{model['id']}: missing required file pattern {item['path']}"
            if item.get("known_incomplete"):
                msg += " (known incomplete Step-3.7 Q3_K_M shard 2)"
            if item.get("required", True):
                errors.append(msg)
            else:
                warnings.append(msg)
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

case "${1:-verify}" in
  sync) sync_models ;;
  verify) verify_models ;;
  *) die "models command must be sync or verify" 64 ;;
esac
