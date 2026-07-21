# Deployment

This guide documents the current root-command deployment surface. It assumes DGX Spark runs Ubuntu 24.04 on aarch64 and services stay bound to `127.0.0.1`.

## Configure

```bash
cd /home/Developer/overseaark
cp .env.example .env
```

Important defaults:

```bash
OVERSEAARK_ROOT=/home/Developer/overseaark
OVERSEAARK_MODELS_DIR=/home/Developer/overseaark-models
OVERSEAARK_DATA_DIR=/home/Developer/overseaark-data
OVERSEAARK_BACKEND_PORT=8000
OVERSEAARK_FRONTEND_PORT=3000
OVERSEAARK_HOST=127.0.0.1
OVERSEAARK_ADAPTER_MODE=command
```

`OVERSEAARK_FRONTEND_PORT` remains in the env file for compatibility, but production frontend assets are mounted by FastAPI on `OVERSEAARK_BACKEND_PORT` when `runtime/frontend-dist` exists. If operating from `root` with a different checkout path, edit `.env` before running bootstrap.

The `.env` copy is optional when the documented DGX paths and port are acceptable. The repository auto-selects command mode on Linux aarch64 with NVIDIA available.

## One-command Start

The normal DGX entrypoint is:

```bash
./overseaark start
```

It performs an idempotent dependency preflight, invokes bootstrap only when needed, verifies locked model sizes and SHA256 values, repairs missing/corrupt files through resumable downloads, starts the app, and requires the health endpoint to pass. Concurrent start/bootstrap operations are excluded by a host lock. Network interruption is recoverable by rerunning the same command.

The first download is about 152 GB. `OVERSEAARK_AUTO_BOOTSTRAP=0` and `OVERSEAARK_AUTO_DOWNLOAD_MODELS=0` convert startup to strict fail-fast mode.

For the target mainland network, dependency bootstrap defaults to `OVERSEAARK_PYPI_INDEX=https://mirrors.aliyun.com/pypi/simple`, rewrites Git transport through `OVERSEAARK_GITHUB_GIT_PREFIX=https://gh-proxy.com/https://github.com/`, and routes pinned Cosmos release wheels through `OVERSEAARK_GITHUB_ASSET_PREFIX=https://ghfast.top/`. Locked Git commits plus uv/model SHA256 values remain the integrity authority. Operators may replace any mirror; an empty Git or asset prefix uses GitHub directly.

## Explicit Bootstrap

Mock mode, local smoke only. This must override `.env.example`, which defaults to command mode:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark bootstrap
```

Production-like bootstrap:

```bash
./overseaark bootstrap
```

Bootstrap behavior:

- Installs system media tools, then verifies and installs the official Node.js `22.23.1` aarch64 archive by SHA-256 when Node 22 is absent.
- Creates backend Python environment with `uv sync` or `backend/.venv`.
- Builds the frontend.
- Creates heavy adapter environments unless `OVERSEAARK_MOCK_MODE=1`.
- Syncs models unless `OVERSEAARK_SKIP_MODELS=1`.

Heavy framework pins installed by bootstrap:

| Purpose | Framework | Commit |
| --- | --- | --- |
| Step-3.7 LLM/VLM | ggml-org/llama.cpp | `76f46ad29d61fd8c1401e8221842934bf62a6064` |
| Step1X image | Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| Cosmos3 video | NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| ASR/TTS | NVIDIA-NeMo/NeMo | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |

## Model Directories

`model-manifest.lock.json` pins the expected model layout under `OVERSEAARK_MODELS_DIR`:

```text
stepfun/step-3.7-flash/
stepfun/step1x-edit-v1p2/
nvidia/cosmos-predict2-0.6b-text2image/
nvidia/cosmos3-edge/
nvidia/nemotron-3.5-asr-streaming-0.6b/
nvidia/magpie_tts_multilingual_357m/
```

Step-3.7 can adopt an existing verified directory from:

```text
/root/models/step-3.7-flash
```

Verify models:

```bash
./overseaark models verify
```

Relax model checks for developer smoke:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark models verify
```

## Start and Stop

```bash
./overseaark start
./overseaark status
./overseaark logs all
./overseaark stop
```

`start` is safe to repeat after completion: valid dependencies and model files are reused, and an already-running healthy backend is retained.

Current service layout:

| Service | Bind | Notes |
| --- | --- | --- |
| Backend API + frontend | `127.0.0.1:8000` | FastAPI `app.main:app`; mounts `runtime/frontend-dist` with SPA fallback if built. |

## SSH Tunnel

From the local machine:

```bash
ssh -p 6105 \
  -L 8000:127.0.0.1:8000 \
  root@106.13.186.155
```

Open:

- Backend API: `http://127.0.0.1:8000/api/v1/health`
- Backend OpenAPI: `http://127.0.0.1:8000/docs`
- Frontend app: `http://127.0.0.1:8000`

Do not expose DGX services directly on public interfaces.

## API Smoke

Health:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

Models:

```bash
curl -sS http://127.0.0.1:8000/api/v1/models
```

Campaign with product image:

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

## Command Adapter Contracts

All adapter commands receive JSON on stdin and return JSON on stdout.

LLM command receives:

```json
{"task":"market_positioning","description":"...","source_market":"CN","target_markets":["US"],"languages":["zh","en","ja"]}
```

Image command receives:

```json
{"prompt":"...","source_image":"/path/product.png","output_path":"/path/visual_design.png"}
```

Video command receives:

```json
{"prompt":"15 second localized product ad","image_path":"/path/visual_design.png","output_path":"/path/campaign_video.mp4"}
```

ASR command receives:

```json
{"audio_path":"/path/demo.wav","language":"auto"}
```

TTS command receives:

```json
{"text":"...","language":"en","output_path":"/path/voice_en.wav"}
```

## Tests and Benchmarks

Root smoke:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark doctor
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark models verify
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark test
```

Backend direct test path:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
```

Frontend:

```bash
cd frontend
npm test
npm run build
```

Benchmark smoke:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark benchmark audio
```

With command mode and verified models, the same four benchmark commands invoke the real local adapter processes. `benchmark audio` performs three cycles across zh/en/ja, two Magpie voices per language, specified and automatic ASR, and writes its evidence to `OVERSEAARK_DATA_DIR/benchmarks/`.

Current mock validation coverage is 19 backend tests, 7 frontend tests, 14 E2E mock contract tests, and an adversarial shell lifecycle suite for auto-repair behavior. A DGX command-mode Step-3.7 schema run reached the 900-second safety limit and verified process-group/CUDA cleanup, but did not satisfy the result contract. Do not claim the 10-minute full-flow target, ASR WER, TTS MOS, Step-3.7 quality, image quality, or Cosmos video quality until the corresponding DGX acceptance run passes.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `bootstrap finished but runtime dependency preflight still fails` | A pinned heavy environment did not finish installing | Rerun `./overseaark start`; downloads/install caches are reused. Inspect the preceding package error if it repeats. |
| Frontend falls back to degraded preview | Backend unavailable or API failure | Check `./overseaark status`, `./overseaark logs backend`, and `http://127.0.0.1:8000/api/v1/health`. |
| `command adapter mode requires commands for...` | Missing command envs | Use `local_runtime_env` defaults through `./overseaark start` or set all `OVERSEAARK_*_COMMAND` variables. |
| Step-3.7 adapter exits with missing `llama-cli` | `OVERSEAARK_LLAMA_CLI` path is absent | Rerun `./overseaark start`; automatic bootstrap builds the pinned CUDA target. |
| Model verification fails | Missing, truncated, or SHA-mismatched file | Rerun `./overseaark start`; the invalid locked file is removed and only the incomplete model is fetched. |
| Upload rejected with 415 | Unsupported content type | Use PNG/JPEG/WebP for products and WAV/MP3/M4A/WebM for audio. |
