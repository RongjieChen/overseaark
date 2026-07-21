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
OVERSEAARK_STEP1X_STEPS=6
OVERSEAARK_COSMOS_STEPS=28
```

`OVERSEAARK_FRONTEND_PORT` remains for compatibility, but production frontend assets are served by FastAPI on `OVERSEAARK_BACKEND_PORT`.

## Mirrors

The default deployment settings use ModelScope and Hugging Face mirror access for model acquisition, plus TUNA for Python packages:

```bash
MODELSCOPE_ENDPOINT=https://modelscope.cn
HF_ENDPOINT=https://hf-mirror.com
OVERSEAARK_PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
OVERSEAARK_PYPI_FILE_PREFIX=https://pypi.tuna.tsinghua.edu.cn/packages/
OVERSEAARK_PYTORCH_INDEX=https://mirrors.aliyun.com/pytorch-wheels/cu129
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
5. Build pinned CUDA `llama.cpp` `llama-server` when missing.
6. Verify required model directories, sizes, and SHA-256 hashes.
7. Download only missing or invalid locked model files when `OVERSEAARK_AUTO_DOWNLOAD_MODELS=1`.
8. Start local `llama-server` for Qwen3.6 in command mode.
9. Start FastAPI and wait for `/api/v1/health`.

Repeat the same command after a network interruption. Completed downloads and valid locked files are reused.

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
- pinned CUDA `llama.cpp`
- isolated Step1X, Cosmos, ASR, and TTS environments
- Open JTalk dictionary for Japanese Magpie TTS
- model sync unless `OVERSEAARK_SKIP_MODELS=1`

Heavy runtime pins:

| Purpose | Runtime | Pin |
| --- | --- | --- |
| Qwen3.6 LLM/VLM | `ggml-org/llama.cpp` | `76f46ad29d61fd8c1401e8221842934bf62a6064` |
| Step1X image | Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| Cosmos3 video | NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| Nemotron ASR | NVIDIA-NeMo/NeMo | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |
| Magpie TTS | NeMo TTS | `nemo_toolkit[tts]==2.7.3` |

## Model Directories

Required model layout under `OVERSEAARK_MODELS_DIR`:

```text
qwen/qwen3.6-35b-a3b-gguf/
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
./overseaark stop
```

Current service layout:

| Service | Bind | Notes |
| --- | --- | --- |
| FastAPI API + frontend | `127.0.0.1:8000` | `app.main:app`; mounts `runtime/frontend-dist`. |
| Qwen3.6 llama.cpp server | `127.0.0.1:8011` | Started on demand; API-key file stored under `OVERSEAARK_PID_DIR`. |

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

## DGX E2E Evidence

The documentation handoff included five successful real E2E results:

| Run | Result |
| --- | --- |
| Run 1 | Completed after an intermediate fix and rerun of the affected stage. |
| Run 2 | Completed uninterrupted in 10m34s; Japanese ASR threshold retry was exercised. |
| Run 3 | Completed uninterrupted in 10m45s; audio similarity zh `0.833`, en `1.0`, ja `1.0`; 854x480 H.264/AAC output and zip integrity verified. |
| Run 4 | Completed all six stages on first attempts in 590.003s; audio similarity zh `0.933`, en `1.0`, ja `1.0`; 854x480 H.264/AAC output and 23-member zip integrity verified. |
| Run 5 | Completed all stages on first attempts in 604.844s; Chinese QC retried once and passed at `0.889`, with en `1.0` and ja `0.931`; video and 23-member zip verified. |

Treat these as DGX E2E status notes, not a replacement for the benchmark JSON artifacts under `OVERSEAARK_DATA_DIR/benchmarks/`. Run 4 passes the <=10-minute target; because run 5 missed by 4.844 seconds after an audio QC retry, the stricter acceptance criterion requires three new consecutive qualifying runs.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `another start/bootstrap operation is already running` | Host operation lock is active. | Wait for the current start/bootstrap to finish; remove a stale lock only after confirming no owning process exists. |
| `runtime dependencies are incomplete` | Backend/frontend/heavy adapter preflight failed. | Rerun `./overseaark start`; inspect package errors if it repeats. |
| `pinned CUDA llama.cpp is missing` | `llama-server` is absent or wrong revision. | Run `./overseaark bootstrap` on target DGX Spark with CUDA build tools. |
| `Qwen3.6 GGUF is missing` | Required Qwen file missing from model root. | Run `./overseaark models sync` or `./overseaark start`. |
| `model verification failed` | Missing, truncated, unsafe, or SHA-mismatched file. | Rerun `./overseaark start`; invalid locked files are removed and fetched again. |
| Adapter command timed out | A heavy adapter exceeded `OVERSEAARK_ADAPTER_TIMEOUT`. | Inspect adapter logs and increase timeout only when the run is otherwise healthy. |
| `LLM server URL must remain localhost-only` | A remote `OVERSEAARK_LLM_BASE_URL` was configured. | Use the default `http://127.0.0.1:8011`. |
| Frontend unavailable | `runtime/frontend-dist` missing or backend not running. | Rerun `./overseaark start`; check `./overseaark logs all`. |
| Upload rejected with 415 | Unsupported content type or product-image header mismatch. | Use real PNG/JPEG/WebP files and keep the multipart `type=` value accurate. |
