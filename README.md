# OverseaArk

OverseaArk is a local-first multimodal campaign workbench for cross-border marketing demos on NVIDIA DGX Spark. It runs as a monorepo with a FastAPI backend, a Vite TypeScript frontend, local model manifests, and root-level operational scripts.

Current implementation status is mixed and documented deliberately:

- Implemented: FastAPI campaign API, multipart product-image uploads, SQLite campaign/stage/event storage, six product campaign stages, SSE progress, rerun-from-stage, cancel, zip export, mock model hooks, command model hook boundary, adapter scripts, frontend workbench shell, degraded local frontend fallback, root lifecycle scripts.
- Implemented as local adapter scripts but not validated end-to-end on DGX here: Step-3.7 LLM through `llama-cli`, Step1X image, Cosmos3 video, Nemotron ASR, and Magpie TTS.
- Not implemented in code: ComfyUI, OpenClaw, or cloud inference APIs.
- Current production scripts serve the FastAPI API and built frontend from `127.0.0.1:8000` when `runtime/frontend-dist` exists. Do not use a `5173` tunnel for production.

## Repository Layout

```text
backend/                  FastAPI service and tests
frontend/                 Vite TypeScript workbench
runtime/frontend-dist/    ignored frontend build output mounted by FastAPI
scripts/                  Root operations and command adapter scripts
tests/e2e/                stdlib E2E contract tests and mock server
model-manifest.lock.json  Pinned model manifest
docs/                     Architecture, deployment, competition, model docs
```

External runtime paths from `.env.example` are `/home/Developer/overseaark-models` for model weights and `/home/Developer/overseaark-data` for SQLite, uploads, artifacts, logs, and pid files. Generated directories such as `backend/.venv/`, `frontend/node_modules/`, `frontend/dist-tests/`, `runtime/frontend-dist/`, and `*-data/` are not source.

## Six Campaign Stages

The implemented backend pipeline runs:

1. `market_positioning`
2. `buyer_persona`
3. `multilingual_copy`
4. `visual_design`
5. `media_production`
6. `quality_packaging`

Each stage has one retry. After a final failure, later stages are skipped and the campaign becomes `partial` if previous artifacts exist.

## Model Stack

| Role | Model / script | Revision | Pinned bytes | License | Status |
| --- | --- | --- | ---: | --- | --- |
| LLM/VLM | `stepfun-ai/Step-3.7-Flash-GGUF` via `scripts/adapters/llm_step.py` and `llama-cli` | `0b69336d2fd2adfdef9c66e425f7778196c31482` | 97.77 GB | Apache-2.0 | Required; wrapper invokes local `/root/llama.cpp/build/bin/llama-cli` by default. |
| Image | `stepfun-ai/Step1X-Edit-v1p2` via `scripts/adapters/image_step1x.py` | `ca85b97fd19f2235dc0d6fd3633d1319f169e149` | 41.80 GB | Apache-2.0 | Required core image model; script requires pinned Step1X diffusers fork. |
| Optional T2I | `nv-community/Cosmos-Predict2-0.6B-Text2Image` mirror of NVIDIA upstream | ModelScope `master`, upstream `dd55b6858b22ad569976bff207880b8fea839da7` | 4.32 GB | NVIDIA Open Model License | Optional inspiration images only; it is not the video fallback. |
| Video | `nv-community/Cosmos3-Edge` mirror of `nvidia/Cosmos3-Edge` via `scripts/adapters/video_cosmos3.py` | ModelScope `master`, upstream `6f58f6b4c91288838e60b6bcb2cc45d997e961de` | 9.13 GB | NVIDIA Open Model Development Weight License 1.1 | Required; script requires pinned Cosmos framework checkout. |
| ASR | `nvidia/nemotron-3.5-asr-streaming-0.6b` via `scripts/adapters/asr_nemo.py` | `f3d333391852ba876df169dcc9ba902d25b6ab0b` | 2.37 GB | NVIDIA Open Model Development Weight License 1.1 | Required manifest entry; script requires NeMo ASR deps. |
| TTS | `nvidia/magpie_tts_multilingual_357m` via `scripts/adapters/tts_magpie.py` | `34d7e40da85cabc97f92198889b65cea27bc7fd1` | 1.21 GB | NVIDIA Open Model License | Required manifest entry; script requires NeMo TTS deps. |

Pinned framework commits:

| Framework | Commit |
| --- | --- |
| Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| NVIDIA-NeMo/NeMo | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |

See [docs/MODEL_LICENSES.md](docs/MODEL_LICENSES.md).

## Quick Start

Mock/developer mode:

```bash
cp .env.example .env
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark bootstrap
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark start
```

Production-like local binding:

```bash
cp .env.example .env
./overseaark bootstrap
./overseaark start
```

`.env.example` defaults to `OVERSEAARK_ADAPTER_MODE=command`. Mock adapters require explicit environment overrides.

Use:

- App: `http://127.0.0.1:8000`
- Backend API: `http://127.0.0.1:8000/api/v1/health`
- Backend OpenAPI: `http://127.0.0.1:8000/docs`

The frontend defaults to `/api/v1`, matching the backend routes.

## API Examples

Health:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

Models:

```bash
curl -sS http://127.0.0.1:8000/api/v1/models
```

Transcribe uploaded audio:

```bash
curl -sS http://127.0.0.1:8000/api/v1/transcriptions \
  -F 'audio=@demo.wav;type=audio/wav' \
  -F 'language=en'
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

Stream progress after replacing `<campaign_id>`:

```bash
curl -N http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/events
```

Rerun from one stage:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/rerun/media_production
```

## DGX SSH Tunnel

Keep services bound to localhost on DGX:

```bash
ssh -p 6105 \
  -L 8000:127.0.0.1:8000 \
  root@106.13.186.155
```

No production `3000` or `5173` tunnel is needed. Port `5173` is only Vite dev-server mode.

## Verification

Commands to run:

```bash
OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark doctor
OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark models verify
OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark test
```

Current test coverage in the tree: backend tests pass 14 cases, frontend tests pass 7 cases, and the implemented E2E mock contract passes 14 cases. These tests validate orchestration, cancellation races, adapter schemas, API contracts, frontend normalization/build, and mock-mode packaging; they do not prove DGX end-to-end model inference quality.

In DGX command mode, `./overseaark benchmark llm|image|audio|video` invokes the pinned local adapters directly and writes JSON evidence under `/home/Developer/overseaark-data/benchmarks/`. The audio benchmark runs three cycles, two official Magpie voices per language, and both specified-language and automatic Nemotron transcription checks at the `0.75` similarity threshold.

## More Docs

- [PRD v1.1 (Markdown)](docs/PRD-v1.1.md)
- [PRD v1.1 (Word)](docs/出海方舟OverseaArk-PRD-v1.1.docx)
- [PRD v1.0 archive (Word)](docs/出海方舟OverseaArk-PRD-v1.0.docx)
- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Competition Notes](docs/COMPETITION.md)
- [Model Licenses](docs/MODEL_LICENSES.md)
