# Architecture

OverseaArk is a local-first monorepo for NVIDIA DGX Spark. The production path is native host processes, not Docker. The application uses FastAPI, a built Vite frontend, SQLite, local model files, and command adapters around pinned model runtimes.

The runtime excludes ComfyUI, OpenClaw, Ollama, StepFun cloud APIs, NVIDIA hosted inference APIs, and any remote model command URL.

## Topology

```text
Browser
  |
  | http://127.0.0.1:8000
  v
FastAPI app
  +-- Built Vite frontend from runtime/frontend-dist
  +-- REST API under /api/v1
  +-- SSE campaign events
  +-- SQLite Store
  +-- CampaignRunner
  +-- serialized ModelManager
        |
        +-- Qwen3.6 via localhost llama.cpp server
        +-- Step1X image adapter
        +-- Cosmos3-Edge video adapter + Wan2.2 VAE
        +-- Nemotron ASR adapter
        +-- Magpie TTS adapter
```

The root lifecycle starts only one web service: FastAPI on `127.0.0.1:8000`. Vite port `5173` is development-only.

## Backend Components

| Component | File | Responsibility |
| --- | --- | --- |
| App factory | `backend/app/main.py` | Routes, uploads, task scheduling, frontend mount. |
| API models | `backend/app/models.py` | Pydantic response schemas, campaign states, stage names. |
| Store | `backend/app/store.py` | SQLite campaigns, stage state, artifacts, event log, rerun reset. |
| Pipeline | `backend/app/pipeline.py` | Six-stage execution, retries, validation, QC, zip packaging. |
| Adapters | `backend/app/adapters.py` | Mock hooks, command hooks, serialization, subprocess cleanup. |
| Settings | `backend/app/settings.py` | `OVERSEAARK_*` runtime configuration. |

## API Surface

| Method | Path | Body | Behavior |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health` | none | Health status and storage path. |
| `GET` | `/health` | none | Legacy health alias. |
| `GET` | `/api/v1/models` | none | Model ids, adapter mode, offline flag, serialized flag. |
| `POST` | `/api/v1/transcriptions` | multipart `audio`, `language` | Nemotron ASR transcription. |
| `POST` | `/api/v1/campaigns` | multipart `product_image`, `description`, optional `name`, `source_market`, `target_markets`, `languages` | Creates and schedules a campaign. |
| `GET` | `/api/v1/campaigns` | none | Lists campaign details. |
| `GET` | `/api/v1/campaigns/{campaign_id}` | none | Returns campaign detail. |
| `POST` | `/api/v1/campaigns/{campaign_id}/rerun` | none | Reruns from `market_positioning`. |
| `POST` | `/api/v1/campaigns/{campaign_id}/rerun/{stage}` | stage path enum | Reruns from a selected stage. |
| `POST` | `/api/v1/campaigns/{campaign_id}/cancel` | none | Requests cancellation and cancels active task. |
| `GET` | `/api/v1/campaigns/{campaign_id}/export` | none | Returns final or partial zip when available. |
| `GET` | `/api/v1/campaigns/{campaign_id}/events` | SSE | Streams persisted campaign events. |

Image uploads accept `image/jpeg`, `image/png`, and `image/webp` up to 20 MB and validate that the file header matches the declared image type. Audio uploads accept WAV, MP3, M4A, and WebM up to the same size limit.

## Pipeline Stages

| Stage | Adapter | Output contract |
| --- | --- | --- |
| `market_positioning` | Qwen3.6 LLM/VLM | `positioning`, `differentiators`, `market_hypotheses`. |
| `buyer_persona` | Qwen3.6 LLM | Non-empty `personas`. |
| `multilingual_copy` | Qwen3.6 LLM | `copy.zh`, `copy.en`, `copy.ja` with title, headline, selling points, body, email, video script, CTA. |
| `visual_design` | Step1X | Existing `image_path`. |
| `media_production` | Magpie TTS, Cosmos3-Edge, ffmpeg | `voice_<language>.wav`, `campaign_video.mp4`, subtitles. |
| `quality_packaging` | Nemotron ASR, zip writer | `manifest.json`, `qc_report.json`, export zip, `qc.passed=true`. |

Each stage has two attempts total. If the second attempt fails, later stages are skipped and the campaign becomes `partial` when earlier artifacts exist.

## Model Execution

`ModelManager` wraps every model hook with one `asyncio.Lock`. Command mode also calls the LLM control command before adapter transitions:

- LLM tasks start local `llama-server` if needed.
- Image, video, ASR, and TTS tasks stop the LLM server first.
- Subprocess adapters run in their own process group.
- Timeout or cancellation terminates the process group.

This design keeps the DGX Spark unified-memory path serial and makes failures visible at the stage boundary.

## Command Adapter Contract

All command adapters read one JSON object from stdin and write one JSON object to stdout. A non-zero exit, non-object JSON, missing required key, missing output file, or timeout is a stage failure.

Default commands are set by `local_runtime_env`:

```bash
OVERSEAARK_LLM_COMMAND="/usr/bin/env python3 scripts/adapters/llm_step.py"
OVERSEAARK_LLM_CONTROL_COMMAND="./overseaark llm"
OVERSEAARK_IMAGE_COMMAND=".venv-step1x/bin/python scripts/adapters/image_step1x.py"
OVERSEAARK_VIDEO_COMMAND="vendor/cosmos-framework/.venv/bin/python scripts/adapters/video_cosmos3.py"
OVERSEAARK_ASR_COMMAND=".venv-asr/bin/python scripts/adapters/asr_nemo.py"
OVERSEAARK_TTS_COMMAND=".venv-tts/bin/python scripts/adapters/tts_magpie.py"
```

The LLM adapter does not call `llama-cli`; it calls the local OpenAI-compatible `llama-server` endpoint at `http://127.0.0.1:8011/v1/chat/completions`.

## Model Runtime Details

| Adapter | Runtime detail |
| --- | --- |
| Qwen3.6 | `Qwen3.6-35B-A3B-Q4_K_M.gguf` plus `mmproj-Qwen3.6-35B-A3B-BF16.gguf`; CUDA `llama.cpp`; `--gpu-layers all`; `--ctx-size 32768`; `--parallel 1`; reasoning off. |
| Step1X | `Step1XEditPipelineV1P2`; default `OVERSEAARK_STEP1X_STEPS=6`; thinking and reflection off by default; optional CPU offload. |
| Cosmos3-Edge | `image2video`; 480p; 16:9; 24 fps; 121 frames; default `OVERSEAARK_COSMOS_STEPS=28`; `--parallelism-preset=latency`; `--sampler=unipc`; local Wan2.2 VAE. |
| Nemotron ASR | Restores the pinned `.nemo`; supports `auto`, `zh`, `en`, and `ja` language prompts. |
| Magpie TTS | Isolated TTS venv; uses pinned Magpie checkpoint, NanoCodec checkpoint, ByT5 tokenizer, and Open JTalk dictionary for Japanese. |

## Model Manifest and Packaging

`model-manifest.lock.json` pins model ids, providers, revisions, local directories, file sizes, SHA-256 hashes, and licenses. `./overseaark models verify` rejects unsafe manifest paths and verifies required locked files under `OVERSEAARK_MODELS_DIR`.

The final export manifest records:

- campaign id and languages
- stage artifacts
- QC report
- offline inference flag
- model manifest audit
- collected model calls
- stage attempts

## Frontend

Frontend source lives in `frontend/src`. The production build is copied to `runtime/frontend-dist` and mounted by FastAPI. The UI covers product input, optional transcription, health status, six-stage progress, SSE updates, rerun, cancel, export, and a local degraded preview when the backend is unavailable.

## Offline Boundary

Runtime defaults:

```text
OVERSEAARK_HOST=127.0.0.1
TRANSFORMERS_OFFLINE=1
HF_HUB_OFFLINE=1
HF_DATASETS_OFFLINE=1
NO_PROXY=127.0.0.1,localhost
```

`validate_offline_runtime` rejects non-local LLM URLs and adapter commands containing `http://` or `https://`. Model download is handled separately by `models sync`, which temporarily enables hub access and then verifies the locked files.

## Fallback Labeling

Mock artifacts and frontend local preview artifacts are not final model validation. If Cosmos3-Edge fails and ffmpeg creates a still-image video fallback, the video is labeled `quality: "degraded"` and the `media_production` stage fails validation unless the real Cosmos output succeeds.
