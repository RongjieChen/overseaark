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
  +-- serialized ModelManager + safe-warm coordinator
        |
        +-- Qwen3.6 via localhost native vLLM (prewarmed between campaigns)
        +-- Step1X image adapter (on demand; optional resident worker)
        +-- Cosmos3-Edge + Wan2.2 VAE (on-demand CLI)
        +-- Nemotron ASR resident worker
        +-- Magpie TTS resident worker
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
| Exporter | `backend/app/exporting.py` | Safe asset resolution, language-scoped manifests, complete/per-language ZIP creation. |
| Settings | `backend/app/settings.py` | `OVERSEAARK_*` runtime configuration. |

## API Surface

| Method | Path | Body | Behavior |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health` | none | Health status and storage path. |
| `GET` | `/health` | none | Legacy health alias. |
| `GET` | `/api/v1/models` | none | Model ids, adapter/offline mode, safe-warm policy, configured resident workers, worker readiness/PIDs. |
| `POST` | `/api/v1/transcriptions` | multipart `audio`, `language` | Nemotron ASR transcription. |
| `POST` | `/api/v1/campaigns` | multipart `product_image`, `description`, optional `name`, `source_market`, `target_markets`, `languages` | Creates and schedules a campaign. |
| `GET` | `/api/v1/campaigns` | none | Lists campaign details. |
| `GET` | `/api/v1/campaigns/{campaign_id}` | none | Returns campaign detail. |
| `POST` | `/api/v1/campaigns/{campaign_id}/rerun` | none | Reruns from `market_positioning`. |
| `POST` | `/api/v1/campaigns/{campaign_id}/rerun/{stage}` | stage path enum | Reruns from a selected stage. |
| `POST` | `/api/v1/campaigns/{campaign_id}/cancel` | none | Requests cancellation and cancels active task. |
| `GET` | `/api/v1/campaigns/{campaign_id}/assets/{asset_key}` | none | Streams a validated source/poster/audio/video/QC artifact inline. |
| `GET` | `/api/v1/campaigns/{campaign_id}/export` | optional `language=zh|en|ja` | Builds a complete multilingual ZIP or one language-scoped ZIP for completed/partial campaigns. |
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

After each successful stage, the pipeline stores the updated artifact map before starting the next stage and emits a sequenced SSE event containing that output. The frontend can therefore render market, persona, copy, poster, audio, video, and QC process artifacts during execution rather than waiting for the final ZIP. Media previews use the campaign asset endpoint instead of exposing filesystem paths.

## Model Execution

`ModelManager` wraps every model hook and warmup transition with one `asyncio.Lock`, so only one inference request executes at a time. Command mode uses a safe-warm policy:

- `OVERSEAARK_RESIDENT_ADAPTERS=asr,tts` keeps Nemotron and Magpie loaded in restartable JSONL workers. `image` is accepted as an optional third worker only after measuring headroom.
- Qwen3.6 native vLLM is prewarmed at application startup and again after a campaign reaches a terminal state. With `OVERSEAARK_KEEP_VLLM_RESIDENT=0`, Step1X, Cosmos, ASR, or TTS transitions stop vLLM before their call.
- Step1X is on demand by default; Cosmos is always an on-demand Cosmos Framework CLI process.
- One-shot subprocess adapters run in their own process group. Timeout or cancellation terminates the complete group; resident workers are restarted after a timeout, crash, or adapter-reported fatal error.

The API reports this policy with `all_models_resident=false`. DGX Spark exposes about 119 GiB of unified CPU/GPU memory, but the required raw model files already total about 75.6 GiB before accounting for decoded weights, vLLM KV cache, CUDA contexts, Step1X/Cosmos activations, video buffers, the OS, and filesystem cache. Loading every runtime together would leave an unreliable OOM margin and can make stage transitions fail. Safe-warm reduces repeated ASR/TTS initialization without making the unsupported claim that all models coexist in memory.

## Command Adapter Contract

One-shot command adapters read one JSON object from stdin and write one JSON object to stdout. Resident ASR/TTS and optional Step1X workers use newline-delimited JSON with request ids: a warmup or inference request receives exactly one matching response while the process keeps the loaded model. A non-zero exit, mismatched request id, non-object JSON, missing required key, missing output file, or timeout is a stage failure.

Default commands are set by `local_runtime_env`:

```bash
OVERSEAARK_LLM_COMMAND="/usr/bin/env python3 scripts/adapters/llm_step.py"
OVERSEAARK_LLM_CONTROL_COMMAND="./overseaark llm"
OVERSEAARK_IMAGE_COMMAND=".venv-step1x/bin/python scripts/adapters/image_step1x.py"
OVERSEAARK_VIDEO_COMMAND="vendor/cosmos-framework/.venv/bin/python scripts/adapters/video_cosmos3.py"
OVERSEAARK_ASR_COMMAND=".venv-asr/bin/python scripts/adapters/asr_nemo.py"
OVERSEAARK_TTS_COMMAND=".venv-tts/bin/python scripts/adapters/tts_magpie.py"
```

The LLM adapter calls the local OpenAI-compatible vLLM endpoint at `http://127.0.0.1:8011/v1/chat/completions`.

## Model Runtime Details

| Adapter | Runtime detail |
| --- | --- |
| Qwen3.6 | `nvidia/Qwen3.6-35B-A3B-NVFP4` revision `491c2f1ea524c639598bf8fa787a93fed5a6fbce`; about 23.45 GB of locked files; native vLLM `0.25.1` in `.venv-vllm`; localhost port `8011`; `--tensor-parallel-size 1`; `--kv-cache-dtype fp8`; `--attention-backend flashinfer`; `--moe-backend marlin`; `--max-model-len 262144`; `--max-num-seqs 4`; `--max-num-batched-tokens 8192`; chunked prefill; prefix caching; MTP speculative decoding; Qwen3 reasoning/tool parsers. |
| Step1X | `Step1XEditPipelineV1P2`; default `OVERSEAARK_STEP1X_STEPS=6`; thinking and reflection off by default; optional CPU offload; on demand unless `image` is explicitly added to the resident set. |
| Cosmos3-Edge | `image2video`; 480p; 16:9; 24 fps; 121 frames; default `OVERSEAARK_COSMOS_STEPS=28`; `--parallelism-preset=latency`; `--sampler=unipc`; local Wan2.2 VAE; always on demand. |
| Nemotron ASR | Restores the pinned `.nemo`; supports `auto`, `zh`, `en`, and `ja` language prompts; resident by default. |
| Magpie TTS | Isolated TTS venv; uses pinned Magpie checkpoint, NanoCodec checkpoint, ByT5 tokenizer, and Open JTalk dictionary for Japanese; resident by default. |

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

The complete ZIP is built on request for every completed or partial campaign. It contains `shared/` assets plus one folder for each language requested by the campaign (`zh/`, `en/`, and/or `ja/`). Each language folder contains localized `copy.json` and `audio.wav` when available. `GET .../export?language=en` filters copy, audio, QC, stages, model calls, and manifest metadata to English; it includes the video only when the composed video's narration language is also English. Legacy top-level filenames are retained in the complete archive for compatibility.

Asset delivery accepts only the explicit keys `source`, `poster`, `video`, `qc`, and `audio-{zh|en|ja}`. Both source uploads and generated files are resolved against their campaign-owned roots; path traversal, symlink escape, and unrelated absolute paths are rejected.

## Frontend

Frontend source lives in `frontend/src`. The production build is copied to `runtime/frontend-dist` and mounted by FastAPI. The UI defaults to Simplified Chinese and can switch to persistent English without changing backend or model-generated payloads. The preference is stored in browser storage and survives refreshes.

The workbench includes a repository-owned **一键填入示例 / Fill demo** image and localized form preset. During a campaign, the localized-output tabs show only the selected `zh`, `en`, or `ja` copy and audio, while a separate six-stage artifact view shows all available intermediate outputs and media/QC previews. Export actions map to the complete ZIP and the currently selected language ZIP. The UI also covers optional transcription, health and model status, resumable SSE progress, rerun, cancel, and a clearly labeled local degraded preview when the backend is unavailable.

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
