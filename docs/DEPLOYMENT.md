# Deployment

This guide documents the current native DGX Spark deployment path. It assumes Ubuntu 24.04 aarch64, NVIDIA CUDA tools, local model storage, and services bound to `127.0.0.1`. There is no Docker deployment path.

## Configure

From the repository root:

```bash
cd /home/Developer/overseaark
cp .env.example .env
```

Copying `.env` is optional when the defaults are acceptable. Shell-provided environment variables override values loaded from `.env`.

Important defaults:

```bash
OVERSEAARK_ROOT=/home/Developer/overseaark
OVERSEAARK_MODELS_DIR=/home/Developer/overseaark-models
OVERSEAARK_DATA_DIR=/home/Developer/overseaark-data
OVERSEAARK_LOG_DIR=/home/Developer/overseaark-data/logs
OVERSEAARK_PID_DIR=/home/Developer/overseaark-data/run
OVERSEAARK_HOST=127.0.0.1
OVERSEAARK_BACKEND_PORT=8000
OVERSEAARK_ADAPTER_MODE=command
OVERSEAARK_RESIDENT_ADAPTERS=asr,tts
OVERSEAARK_KEEP_VLLM_RESIDENT=0
OVERSEAARK_STEP1X_STEPS=6
OVERSEAARK_COSMOS_STEPS=28
OVERSEAARK_VLLM_ENV_DIR=/home/Developer/overseaark/.venv-vllm
OVERSEAARK_VLLM_PORT=8011
OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION=0.4
OVERSEAARK_VLLM_MAX_MODEL_LEN=262144
OVERSEAARK_VLLM_MAX_NUM_SEQS=4
OVERSEAARK_VLLM_MAX_NUM_BATCHED_TOKENS=8192
```

`OVERSEAARK_FRONTEND_PORT` remains for compatibility, but production frontend assets are served by FastAPI on `OVERSEAARK_BACKEND_PORT`.

## Mirrors

The default deployment settings use ModelScope and Hugging Face mirror access for model acquisition, plus TUNA for Python packages:

```bash
MODELSCOPE_ENDPOINT=https://modelscope.cn
HF_ENDPOINT=https://hf-mirror.com
OVERSEAARK_PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
OVERSEAARK_PYPI_FILE_PREFIX=https://pypi.tuna.tsinghua.edu.cn/packages/
OVERSEAARK_PYTORCH_INDEX=https://mirrors.aliyun.com/pytorch-wheels/cu130
OVERSEAARK_GITHUB_GIT_PREFIX=https://gh-proxy.com/https://github.com/
OVERSEAARK_GITHUB_ASSET_PREFIX=https://ghfast.top/
```

Pinned Git revisions, uv locks, file sizes, and SHA-256 hashes remain the integrity authority even when mirrors are used.

## One-command Start

```bash
./overseaark start
```

Startup performs these checks and repairs:

1. Validate localhost bind and numeric ports.
2. Acquire a host operation lock.
3. Bootstrap missing runtime dependencies when `OVERSEAARK_AUTO_BOOTSTRAP=1`.
4. Build the frontend into `runtime/frontend-dist`.
5. Install the pinned native vLLM ARM64 CUDA wheel into `.venv-vllm` when missing.
6. Verify required model directories, sizes, and SHA-256 hashes.
7. Download only missing or invalid locked model files when `OVERSEAARK_AUTO_DOWNLOAD_MODELS=1`.
8. Start local vLLM for Qwen3.6 in command mode on `127.0.0.1:8011`.
9. Start FastAPI and schedule the configured resident ASR/TTS plus next-campaign LLM warmup in the background.
10. Wait for `/api/v1/health` before returning success.

Repeat the same command after a network interruption. Completed downloads and valid locked files are reused.

Startup waits for the native vLLM health check, then returns as soon as FastAPI is reachable. Resident ASR/TTS warmup continues in the background so a warmup failure cannot take down the UI or health endpoint. Check `/api/v1/health` (`model_status`) and `/api/v1/models` (`residency.warmup`) for `warming`, `ready`, or `degraded`; follow `./overseaark logs all` and `./overseaark logs llm` instead of starting a second copy.

Strict startup:

```bash
OVERSEAARK_AUTO_BOOTSTRAP=0 OVERSEAARK_AUTO_DOWNLOAD_MODELS=0 ./overseaark start
```

## Bootstrap

Mock/developer bootstrap:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark bootstrap
```

Production-like bootstrap:

```bash
./overseaark bootstrap
```

Bootstrap installs or prepares:

- system tools: build essentials, cmake, curl, ffmpeg, git, git-lfs, Python headers, venv support
- Node.js `22.23.1` aarch64 archive, verified by upstream SHA-256
- backend Python environment under `backend/.venv`
- frontend dependencies and production build
- pinned native vLLM ARM64 CUDA wheel in `.venv-vllm`
- isolated Step1X, Cosmos, ASR, and TTS environments
- Open JTalk dictionary for Japanese Magpie TTS
- model sync unless `OVERSEAARK_SKIP_MODELS=1`

Heavy runtime pins:

| Purpose | Runtime | Pin |
| --- | --- | --- |
| Qwen3.6 LLM/VLM | native vLLM ARM64 CUDA wheel | `vLLM 0.25.1`; wheel SHA-256 `bdffbe35b2c1ab8f2a9dcc337b657261d9b192c92c217e5a2f98a8835fe78daa` |
| Step1X image | Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| Cosmos3 video | NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| Nemotron ASR | NVIDIA-NeMo/NeMo | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |
| Magpie TTS | NeMo TTS | `nemo_toolkit[tts]==2.7.3` |

## Model Directories

Required model layout under `OVERSEAARK_MODELS_DIR`:

```text
nvidia/qwen3.6-35b-a3b-nvfp4/
stepfun/step1x-edit-v1p2/
nvidia/cosmos3-edge/
wan/wan2.2-vae/
nvidia/nemotron-3.5-asr-streaming-0.6b/
nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps/
nvidia/magpie_tts_multilingual_357m/
google/byt5-small/
```

Optional model:

```text
nvidia/cosmos-predict2-0.6b-text2image/
```

Verify models:

```bash
./overseaark models verify
```

Download or repair models:

```bash
./overseaark models sync
```

Sync optional Cosmos-Predict2:

```bash
OVERSEAARK_SYNC_OPTIONAL_MODELS=1 ./overseaark models sync
```

Relax checks for local smoke runs:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark models verify
```

## Operations

```bash
./overseaark start
./overseaark status
./overseaark logs all
./overseaark logs llm
./overseaark llm status
./overseaark llm stop
./overseaark stop
```

`./overseaark llm stop` stops the native vLLM process on demand and releases the Qwen runtime before other heavy GPU adapters run. To force a clean vLLM reinstall, stop the service, remove `.venv-vllm`, then rerun `./overseaark bootstrap`.

Inspect the effective warm policy and worker process ids through the API:

```bash
curl -sS http://127.0.0.1:8000/api/v1/models
```

The response intentionally reports `all_models_resident: false`. Under the default profile, `residency.resident_adapters` is `asr,tts`, worker entries expose readiness/PIDs, `llm_policy` is `prewarmed-between-campaigns`, and `video_policy` is `on-demand-cosmos-cli`.

Current service layout:

| Service | Bind | Notes |
| --- | --- | --- |
| FastAPI API + frontend | `127.0.0.1:8000` | `app.main:app`; mounts `runtime/frontend-dist`. |
| Qwen3.6 native vLLM server | `127.0.0.1:8011` | Prewarmed by lifecycle/backend, released before heavy non-LLM stages, and restarted when needed; API-key file under `OVERSEAARK_PID_DIR`. |
| Nemotron ASR / Magpie TTS workers | no TCP bind | Long-lived backend child processes using request-id JSONL over stdio. |

vLLM uses the official DGX Spark-oriented lifecycle parameters from `scripts/vllm_server.sh`: `--tensor-parallel-size 1`, `--kv-cache-dtype fp8`, `--attention-backend flashinfer`, `--moe-backend marlin`, `--gpu-memory-utilization 0.4`, `--max-model-len 262144`, `--max-num-seqs 4`, `--max-num-batched-tokens 8192`, chunked prefill, prefix caching, MTP speculative decoding, `--load-format fastsafetensors`, `--reasoning-parser qwen3`, and Qwen3 XML tool-call parsing.

The first GB10 start also compiles FlashInfer SM121 kernels. `MAX_JOBS=1` and `CMAKE_BUILD_PARALLEL_LEVEL=1` deliberately serialize this JIT work so compiler processes do not contend with loaded weights in unified memory. The verified cold-cache start reached health in 526 seconds; once caches existed, a full model-hash verification plus restart reached health in 166 seconds.

## Safe-warm Model Policy

The supported default is:

```bash
OVERSEAARK_RESIDENT_ADAPTERS=asr,tts
OVERSEAARK_KEEP_VLLM_RESIDENT=0
```

- Nemotron ASR and Magpie TTS load once and remain ready inside restartable resident workers.
- vLLM is prewarmed at backend startup and after a campaign reaches a terminal state. It stays ready through LLM work and is released before Step1X/Cosmos or speech inference.
- Step1X is on demand by default. Operators may test `OVERSEAARK_RESIDENT_ADAPTERS=asr,tts,image`, but this is opt-in and must be validated with unified-memory monitoring and repeated campaigns.
- Cosmos3-Edge remains an on-demand Cosmos Framework CLI process; `video` is not accepted in `OVERSEAARK_RESIDENT_ADAPTERS`.

Do not keep every model resident merely because DGX Spark reports about 119 GiB of unified memory. Required locked files total about 81.2 GB decimal (75.6 GiB), and files on disk are not the full runtime cost: vLLM KV cache, decoded model tensors, CUDA contexts, Step1X/Cosmos activations, VAE/video buffers, the OS, and filesystem cache need additional and sometimes overlapping space. The safe profile preserves OOM margin at model transitions; an all-resident configuration is unsupported.

After changing the profile, restart and verify it:

```bash
./overseaark restart
curl -sS http://127.0.0.1:8000/api/v1/models
free -h
nvidia-smi
```

## GPU and Unified-memory Monitoring

Run monitoring commands in the DGX Spark SSH session while the browser campaign is active:

```bash
# Snapshot: GPU utilization, temperature, power, and active processes
nvidia-smi

# Continuous device metrics; Ctrl-C to stop
nvidia-smi dmon -s pucvmet

# Unified CPU/GPU memory headroom
free -h
```

If the demo monitor is enabled, follow its persisted output with:

```bash
tail -f /home/Developer/overseaark-data/logs/gpu-dmon.log
```

The web workbench contains an expandable GPU command guide, but it does not stream privileged device metrics into the browser. Some DGX Spark per-process GPU-memory columns may show `N/A`; use `free -h` to judge total unified-memory pressure.

## SSH Tunnel

From the local machine:

```bash
ssh -p 6105 \
  -L 8000:127.0.0.1:8000 \
  root@106.13.186.155
```

Open:

- App: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/v1/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

Do not expose DGX services directly on public interfaces.

## API Smoke

These commands require a running service.

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
curl -sS http://127.0.0.1:8000/api/v1/models
```

Create a campaign:

```bash
curl -sS http://127.0.0.1:8000/api/v1/campaigns \
  -F 'product_image=@product.png;type=image/png' \
  -F 'name=Travel charger launch' \
  -F 'description=A compact smart travel charger for global shoppers.' \
  -F 'source_market=CN' \
  -F 'target_markets=US,JP' \
  -F 'languages=zh,en,ja'
```

Transcription:

```bash
curl -sS http://127.0.0.1:8000/api/v1/transcriptions \
  -F 'audio=@demo.wav;type=audio/wav' \
  -F 'language=auto'
```

After capturing the returned campaign id, inspect persisted progress and artifacts:

```bash
curl -sS http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>
curl -N http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/events
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/poster
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/audio-en
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/video
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/qc
```

Asset keys are restricted to `source`, `poster`, `video`, `qc`, `audio-zh`, `audio-en`, and `audio-ja`. A key returns 404 until the producing stage has stored the artifact.

Download the complete multilingual ZIP or one requested language:

```bash
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export
curl -OJ 'http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export?language=en'
```

The complete archive has `shared/` and one folder per requested language. A single-language archive contains only that language's localized copy/audio and filtered metadata; a video is present only when its narration language matches the requested language.

## Command Adapter Payloads

LLM:

```json
{"task":"market_positioning","description":"...","source_market":"CN","target_markets":["US"],"languages":["zh","en","ja"],"product_image_path":"/path/product.png"}
```

Image:

```json
{"prompt":"...","source_image":"/path/product.png","output_path":"/path/visual_design.png","overlay_text":"Ready for every journey"}
```

Video:

```json
{"prompt":"15 second localized product ad","image_path":"/path/visual_design.png","output_path":"/path/cosmos_video.mp4"}
```

ASR:

```json
{"audio_path":"/path/demo.wav","language":"auto"}
```

TTS:

```json
{"text":"...","language":"en","speaker":"Jason","output_path":"/path/voice_en.wav"}
```

## Tests and Benchmarks

Root smoke:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark doctor
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark models verify
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark test
```

The root test command covers backend tests, frontend type/build checks, lifecycle adversarial checks, backend smoke, and Mock HTTP E2E. The suite count is intentionally not frozen in this guide; use the totals printed by the current run.

Backend direct:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
```

Frontend direct:

```bash
cd frontend
npm test
npm run build
```

Direct command-mode benchmarks:

```bash
./overseaark benchmark llm
./overseaark benchmark image
./overseaark benchmark audio
./overseaark benchmark video
```

Reports are written under `OVERSEAARK_DATA_DIR/benchmarks/`.

Browser acceptance after a deployed `start`:

1. Open `http://127.0.0.1:8000`; confirm Chinese is the default UI, switch to English, refresh, and confirm the choice persists.
2. Click **一键填入示例 / Fill demo** and verify the bundled image plus complete campaign form appear before submission.
3. Create the campaign and confirm six-stage SSE progress continues across a refresh.
4. Confirm completed-stage outputs appear in **阶段过程产物 / Stage artifacts** while a later stage is still running; verify poster/audio/video/QC controls when each becomes available.
5. Switch the `zh`, `en`, and `ja` output tabs and verify copy/audio do not leak across languages.
6. Download the complete ZIP and the current-language ZIP; inspect `shared/` plus language folders and validate that the scoped archive excludes other-language copy, audio, QC, and model-call metadata.
7. During real DGX inference, watch `nvidia-smi dmon -s pucvmet` and `free -h`; after completion, check `/api/v1/models` for ready resident workers and scan logs for OOM, CUDA-context, or unexpected worker restarts.

## DGX E2E Evidence

The historical DGX handoff included successful real E2E results on the previous LLM runtime:

| Run | Result |
| --- | --- |
| Run 1 | Completed after an intermediate fix and rerun of the affected stage. |
| Run 2 | Completed uninterrupted in 10m34s; Japanese ASR threshold retry was exercised. |
| Run 3 | Completed uninterrupted in 10m45s; audio similarity zh `0.833`, en `1.0`, ja `1.0`; 854x480 H.264/AAC output and zip integrity verified. |
| Run 4 | Completed all six stages on first attempts in 590.003s; audio similarity zh `0.933`, en `1.0`, ja `1.0`; 854x480 H.264/AAC output and 23-member zip integrity verified. |
| Run 5 | Completed all stages on first attempts in 604.844s; Chinese QC retried once and passed at `0.889`, with en `1.0` and ja `0.931`; video and 23-member zip verified. |
| Run 7 | Old-runtime cold-start run completed in 9m12s. Keep this as legacy evidence only; it is not vLLM acceptance evidence. |
| Run 8 | Native vLLM reached every generation stage, then remained `partial` after mixed-script Chinese narration failed the fixed `0.75` ASR threshold across retries. |
| Run 9 | Native vLLM completed all six stages on first attempts in `580.147s`; zh/en/ja similarity `0.9375`/`1.0`/`0.9189`; real 854x480 H.264/AAC video and 23-member ZIP verified. |

Treat these as DGX E2E status notes, not a replacement for benchmark JSON under `OVERSEAARK_DATA_DIR/benchmarks/`. Run 9 is the first qualifying native vLLM <=10-minute result. The stricter acceptance criterion still requires two further consecutive qualifying native vLLM campaigns after run 9.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `another start/bootstrap operation is already running` | Host operation lock is active. | Wait for the current start/bootstrap to finish; remove a stale lock only after confirming no owning process exists. |
| `runtime dependencies are incomplete` | Backend/frontend/heavy adapter preflight failed. | Rerun `./overseaark start`; inspect package errors if it repeats. |
| `pinned native vLLM is missing` | `.venv-vllm` is absent or does not contain the pinned CUDA ARM64 wheel. | Run `./overseaark bootstrap`; remove `.venv-vllm` first only when forcing a clean reinstall. |
| `Qwen3.6 NVFP4 is missing` | Required Qwen file missing from model root. | Run `./overseaark models sync` or `./overseaark start`. |
| `model verification failed` | Missing, truncated, unsafe, or SHA-mismatched file. | Rerun `./overseaark start`; invalid locked files are removed and fetched again. |
| Adapter command timed out | A heavy adapter exceeded `OVERSEAARK_ADAPTER_TIMEOUT`. | Inspect adapter logs and increase timeout only when the run is otherwise healthy. |
| Backend warmup fails or a resident worker repeatedly restarts | A resident runtime failed to load or the warm profile exceeds current headroom. | Restore `OVERSEAARK_RESIDENT_ADAPTERS=asr,tts` and `OVERSEAARK_KEEP_VLLM_RESIDENT=0`, restart, then inspect backend logs, `/api/v1/models`, `free -h`, and `nvidia-smi`. |
| OOM during Step1X/Cosmos transition | Too many models were kept warm or another process is consuming unified memory. | Remove `image` from `OVERSEAARK_RESIDENT_ADAPTERS`, keep vLLM residency disabled, stop unrelated GPU processes, and rerun from the failed stage. |
| `LLM server URL must remain localhost-only` | A remote `OVERSEAARK_LLM_BASE_URL` was configured. | Use the default `http://127.0.0.1:8011`. |
| Frontend unavailable | `runtime/frontend-dist` missing or backend not running. | Rerun `./overseaark start`; check `./overseaark logs all`. |
| Upload rejected with 415 | Unsupported content type or product-image header mismatch. | Use real PNG/JPEG/WebP files and keep the multipart `type=` value accurate. |
| Asset endpoint returns 404 | The producing stage has not succeeded, the campaign lacks that language, or the key is invalid. | Wait for the relevant stage and use only `source`, `poster`, `video`, `qc`, or `audio-{zh|en|ja}`. |
| Single-language export returns 422 | The language is unsupported or was not requested for that campaign. | Use `zh`, `en`, or `ja` and select a language included at campaign creation. |
