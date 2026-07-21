#!/usr/bin/env bash
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

VLLM_MODEL_ID="nvidia/Qwen3.6-35B-A3B-NVFP4"
VLLM_MODEL_DIR="$OVERSEAARK_MODELS_DIR/nvidia/qwen3.6-35b-a3b-nvfp4"

vllm_image_present() {
  "$OVERSEAARK_DOCKER" image inspect "$OVERSEAARK_VLLM_IMAGE_LOCAL" >/dev/null 2>&1
}

pull_vllm_image() {
  have "$OVERSEAARK_DOCKER" || die "Docker is required for the NVIDIA vLLM runtime"
  vllm_image_present && return 0

  local source="$OVERSEAARK_VLLM_IMAGE_SOURCE"
  local pulled="$source"
  log "pulling pinned vLLM image $source"
  if ! "$OVERSEAARK_DOCKER" pull --platform linux/arm64 "$source"; then
    [[ -n "$OVERSEAARK_DOCKERHUB_PREFIX" ]] || return 1
    pulled="${OVERSEAARK_DOCKERHUB_PREFIX}${source}"
    warn "direct Docker Hub pull failed; retrying through $OVERSEAARK_DOCKERHUB_PREFIX"
    "$OVERSEAARK_DOCKER" pull --platform linux/arm64 "$pulled"
  fi
  "$OVERSEAARK_DOCKER" tag "$pulled" "$OVERSEAARK_VLLM_IMAGE_LOCAL"
  local architecture
  architecture="$("$OVERSEAARK_DOCKER" image inspect \
    --format '{{.Architecture}}' "$OVERSEAARK_VLLM_IMAGE_LOCAL")"
  [[ "$architecture" == "arm64" ]] || \
    die "pinned vLLM image architecture is $architecture, expected arm64"
}

vllm_container_exists() {
  "$OVERSEAARK_DOCKER" container inspect "$OVERSEAARK_VLLM_CONTAINER" >/dev/null 2>&1
}

vllm_container_running() {
  [[ "$("$OVERSEAARK_DOCKER" inspect \
    --format '{{.State.Running}}' "$OVERSEAARK_VLLM_CONTAINER" 2>/dev/null || true)" == "true" ]]
}

vllm_health() {
  vllm_container_running || return 1
  "$OVERSEAARK_DOCKER" exec "$OVERSEAARK_VLLM_CONTAINER" python3 -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${OVERSEAARK_VLLM_PORT}/health', timeout=2).read()" \
    >/dev/null 2>&1
}

start_vllm() {
  [[ -f "$VLLM_MODEL_DIR/config.json" ]] || \
    die "Qwen model is missing at $VLLM_MODEL_DIR; run ./overseaark models sync"
  vllm_image_present || die "pinned vLLM image is missing; run ./overseaark bootstrap"
  if vllm_health; then
    log "vLLM already healthy in container $OVERSEAARK_VLLM_CONTAINER"
    return 0
  fi
  if vllm_container_exists; then
    "$OVERSEAARK_DOCKER" rm -f "$OVERSEAARK_VLLM_CONTAINER" >/dev/null
  fi

  log "starting network-isolated vLLM for $VLLM_MODEL_ID"
  "$OVERSEAARK_DOCKER" run -d \
    --name "$OVERSEAARK_VLLM_CONTAINER" \
    --label com.overseaark.service=vllm \
    --network none \
    --gpus all \
    --ipc host \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    -e HF_HUB_OFFLINE=1 \
    -e TRANSFORMERS_OFFLINE=1 \
    -e HF_DATASETS_OFFLINE=1 \
    -v "$VLLM_MODEL_DIR:/model:ro" \
    "$OVERSEAARK_VLLM_IMAGE_LOCAL" \
    /model \
    --served-model-name "$VLLM_MODEL_ID" \
    --host 127.0.0.1 \
    --port "$OVERSEAARK_VLLM_PORT" \
    --tensor-parallel-size 1 \
    --trust-remote-code \
    --quantization modelopt \
    --kv-cache-dtype fp8 \
    --attention-backend flashinfer \
    --moe-backend marlin \
    --gpu-memory-utilization "$OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION" \
    --max-model-len "$OVERSEAARK_VLLM_MAX_MODEL_LEN" \
    --max-num-seqs 1 \
    --max-num-batched-tokens 8192 \
    --enable-chunked-prefill \
    --async-scheduling \
    --enable-prefix-caching \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}' \
    --load-format fastsafetensors \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice >/dev/null

  local deadline=$((SECONDS + OVERSEAARK_VLLM_STARTUP_TIMEOUT))
  local next_progress=$((SECONDS + 15))
  while (( SECONDS < deadline )); do
    if vllm_health; then
      log "vLLM health check passed"
      return 0
    fi
    if ! vllm_container_running; then
      warn "vLLM container exited during startup"
      "$OVERSEAARK_DOCKER" logs --tail 120 "$OVERSEAARK_VLLM_CONTAINER" >&2 || true
      return 1
    fi
    if (( SECONDS >= next_progress )); then
      log "waiting for vLLM model load (${SECONDS}s elapsed)"
      next_progress=$((SECONDS + 15))
    fi
    sleep 2
  done
  warn "vLLM did not become healthy within ${OVERSEAARK_VLLM_STARTUP_TIMEOUT}s"
  "$OVERSEAARK_DOCKER" logs --tail 120 "$OVERSEAARK_VLLM_CONTAINER" >&2 || true
  return 1
}

stop_vllm() {
  if ! vllm_container_exists; then
    log "vLLM stopped"
    return 0
  fi
  log "stopping vLLM container $OVERSEAARK_VLLM_CONTAINER"
  "$OVERSEAARK_DOCKER" stop --time 20 "$OVERSEAARK_VLLM_CONTAINER" >/dev/null || true
  "$OVERSEAARK_DOCKER" rm "$OVERSEAARK_VLLM_CONTAINER" >/dev/null 2>&1 || true
  log "vLLM stopped"
}

status_vllm() {
  if vllm_health; then
    local network
    network="$("$OVERSEAARK_DOCKER" inspect \
      --format '{{.HostConfig.NetworkMode}}' "$OVERSEAARK_VLLM_CONTAINER")"
    printf '%-10s healthy container=%s network=%s\n' \
      "vllm" "$OVERSEAARK_VLLM_CONTAINER" "$network"
  elif vllm_container_running; then
    printf '%-10s loading container=%s\n' "vllm" "$OVERSEAARK_VLLM_CONTAINER"
  else
    printf '%-10s stopped\n' "vllm"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-status}" in
    image) pull_vllm_image ;;
    start) start_vllm ;;
    stop) stop_vllm ;;
    health) vllm_health ;;
    status) status_vllm ;;
    logs) exec "$OVERSEAARK_DOCKER" logs --tail 120 -f "$OVERSEAARK_VLLM_CONTAINER" ;;
    *) die "vllm command must be image, start, stop, health, status, or logs" 64 ;;
  esac
fi
