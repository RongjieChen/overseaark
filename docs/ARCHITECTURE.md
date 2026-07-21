# Architecture

OverseaArk is a local-first monorepo. The approved runtime path is local DGX Spark services reached through localhost SSH tunnels. It does not use ComfyUI, OpenClaw, StepFun cloud APIs, NVIDIA hosted inference APIs, or other cloud inference APIs.

## Workshop reference

The supplied `workshop-Copy1(1).ipynb` was used as an operational reference, not as an application dependency. OverseaArk keeps the useful DGX Spark patterns from that workshop—localhost-only services, explicit PID/log lifecycle scripts, health checks, SSH tunnelling, and releasing one model before loading the next on unified memory. Its Ollama, ComfyUI, OpenClaw, insecure browser-token, and notebook-driven orchestration paths are intentionally excluded; the production path is FastAPI plus direct local model adapters.

## Current Topology

```text
Browser
  |
  | production script path: http://127.0.0.1:8000
  v
Built Vite frontend mounted by FastAPI from runtime/frontend-dist
  |
  | REST + SSE, API base /api/v1
  v
FastAPI backend on http://127.0.0.1:8000
  |
  +-- SQLite store
  +-- CampaignRunner
  +-- serialized ModelManager
  +-- mock hooks or command hooks
  |
  +-- scripts/adapters/llm_step.py
  +-- scripts/adapters/image_step1x.py
  +-- scripts/adapters/video_cosmos3.py
  +-- scripts/adapters/asr_nemo.py
  +-- scripts/adapters/tts_magpie.py
```

FastAPI mounts frontend assets from `runtime/frontend-dist` when that build directory exists. Vite dev server port `5173` is development-only.

## Backend Components

| Component | File | Responsibility |
| --- | --- | --- |
| App factory | `backend/app/main.py` | Routes, upload validation, app state, background scheduling. |
| Models | `backend/app/models.py` | Pydantic schemas and six stage names. |
| Store | `backend/app/store.py` | SQLite campaigns, stages, artifacts, events, rerun reset. |
| Pipeline | `backend/app/pipeline.py` | Six-stage campaign execution, retry, partial failure, zip packaging. |
| Adapters | `backend/app/adapters.py` | Mock hooks, command hooks, serialized model access. |
| Settings | `backend/app/settings.py` | `OVERSEAARK_*` paths and command environment. |

## Backend API

| Method | Path | Body | Status |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health` | none | Implemented |
| `GET` | `/health` | none | Implemented legacy alias |
| `GET` | `/api/v1/models` | none | Implemented |
| `POST` | `/api/v1/transcriptions` | multipart `audio`, `language` | Implemented |
| `POST` | `/api/v1/campaigns` | multipart `product_image`, `description`, optional `name`, `source_market`, `target_markets`, `languages` | Implemented |
| `GET` | `/api/v1/campaigns` | none | Implemented |
| `GET` | `/api/v1/campaigns/{campaign_id}` | none | Implemented |
| `POST` | `/api/v1/campaigns/{campaign_id}/rerun` | none | Implemented |
| `POST` | `/api/v1/campaigns/{campaign_id}/rerun/{stage}` | stage path enum | Implemented |
| `POST` | `/api/v1/campaigns/{campaign_id}/cancel` | none | Implemented |
| `GET` | `/api/v1/campaigns/{campaign_id}/export` | none | Implemented |
| `GET` | `/api/v1/campaigns/{campaign_id}/events` | SSE | Implemented |

Upload validation accepts product images with content types `image/jpeg`, `image/png`, or `image/webp`, with a 20 MB limit.

## Six Product Stages

| Stage | Model hook | Output |
| --- | --- | --- |
| `market_positioning` | LLM | Positioning, differentiators, target market context. |
| `buyer_persona` | LLM | Buyer personas and decision triggers. |
| `multilingual_copy` | LLM | Copy for requested languages. |
| `visual_design` | Step1X image | `visual_design.png`. |
| `media_production` | TTS + video | `voice_<language>.wav` and `campaign_video.mp4`. |
| `quality_packaging` | LLM + zip | `manifest.json` and `overseaark-export.zip`. |

Each model call is serialized by `ModelManager` to avoid concurrent heavy model residency on DGX Spark unified memory.

## Adapter Modes

`OVERSEAARK_ADAPTER_MODE=mock` uses deterministic local mock outputs:

- 1x1 PNG image.
- Minimal MP4 bytes.
- Silent WAV audio.
- Mock LLM/ASR/TTS JSON.

`.env.example` sets `OVERSEAARK_ADAPTER_MODE=command`. In command mode the launcher supplies local defaults when these variables are omitted:

```bash
OVERSEAARK_LLM_COMMAND="/usr/bin/env python3 scripts/adapters/llm_step.py"
OVERSEAARK_IMAGE_COMMAND=".venv-step1x/bin/python scripts/adapters/image_step1x.py"
OVERSEAARK_VIDEO_COMMAND="vendor/cosmos-framework/.venv/bin/python scripts/adapters/video_cosmos3.py"
OVERSEAARK_ASR_COMMAND=".venv-nemo/bin/python scripts/adapters/asr_nemo.py"
OVERSEAARK_TTS_COMMAND=".venv-nemo/bin/python scripts/adapters/tts_magpie.py"
```

All command hooks read one JSON object from stdin and write one JSON object to stdout. Non-zero exit or non-object JSON is a stage failure.

Important validation boundary: the command adapter scripts are real integration code, including `llm_step.py`, which invokes `llama-cli` against the pinned Step-3.7 shard. This documentation pass did not validate DGX end-to-end model inference or quality for Step-3.7, Step1X, Cosmos3, Nemotron ASR, or Magpie TTS.

## Framework Pins

Heavy adapter bootstrap pins framework commits:

| Adapter | Framework | Commit |
| --- | --- | --- |
| Step1X image | Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| Cosmos3 video | NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| Nemotron ASR + Magpie TTS | NVIDIA-NeMo/NeMo | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |

## Frontend

Frontend source lives in `frontend/src`. It provides:

- Product form with image upload, description, optional transcription, source language, and target languages.
- Six-stage progress UI.
- SSE progress handling.
- Rerun/cancel/export buttons.
- Degraded local preview when the backend is unavailable.

The frontend default API base is `/api/v1`, and campaign creation uses the backend multipart field names `name`, `description`, `source_market`, `target_markets`, `languages`, and `product_image`.

## Offline and Data Directories

Defaults come from `.env.example`:

```text
OVERSEAARK_ROOT=/home/Developer/overseaark
OVERSEAARK_MODELS_DIR=/home/Developer/overseaark-models
OVERSEAARK_DATA_DIR=/home/Developer/overseaark-data
OVERSEAARK_LOG_DIR=/home/Developer/overseaark-data/logs
OVERSEAARK_PID_DIR=/home/Developer/overseaark-data/run
OVERSEAARK_HOST=127.0.0.1
OVERSEAARK_BACKEND_PORT=8000
OVERSEAARK_FRONTEND_PORT=3000
OVERSEAARK_ADAPTER_MODE=command
TRANSFORMERS_OFFLINE=1
HF_HUB_OFFLINE=1
HF_DATASETS_OFFLINE=1
```

The backend stores SQLite state, uploads, and artifacts under `OVERSEAARK_DATA_DIR`.

## Fallback Labeling

The frontend's local fallback creates artifacts with `quality: "degraded"`. Cosmos video outputs must also be labeled or described as degraded unless the real local adapter has run successfully and the output has passed quality checks. Do not present mock, placeholder, or fallback artifacts as final model validation.
