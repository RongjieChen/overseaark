# OverseaArk

OverseaArk is a local-first multimodal campaign workbench for cross-border sellers on NVIDIA DGX Spark. The repository is a single monorepo: FastAPI backend, Vite TypeScript frontend, local model adapters, lifecycle scripts, tests, and the pinned model manifest all live here. There is no Docker path and no cloud inference path.

The implemented demo flow accepts one product image and product description, runs six serialized stages, and exports a zip package containing campaign copy, poster, narration audio, composed video, QC report, and model provenance.

## Current Status

- Implemented: root one-command lifecycle, FastAPI API, built frontend mounted by FastAPI, SQLite campaign/event store, multipart uploads, six campaign stages, SSE progress, rerun, cancel, export, mock mode, command adapter mode, model verification/sync, native vLLM LLM runtime, and process-group cleanup for timed-out adapters.
- Implemented command adapters: Qwen3.6 LLM/VLM through localhost native vLLM, Step1X image generation, Cosmos3-Edge video generation, Nemotron ASR, and Magpie TTS.
- Implemented safety boundary: localhost-only serving, no remote model command URLs, offline Hugging Face runtime flags, ModelManager serialization, and one heavy GPU adapter active at a time.
- Not implemented: Docker, ComfyUI, OpenClaw, Ollama, StepFun cloud APIs, NVIDIA hosted inference APIs, or public service binding.
- DGX E2E evidence: native vLLM run 9 completed all six stages on first attempts in `580.147s` (9m40s). It produced a real 854x480 H.264/AAC Cosmos video, a valid 23-member ZIP, and ASR similarities zh `0.9375`, en `1.0`, ja `0.9189`. Run 8 is retained as truthful negative evidence: its Chinese mixed-script `GaN` narration stayed below `0.75` and the campaign remained `partial`, which led to the speech-native prompt fix used by run 9. This establishes one qualifying native vLLM run; three consecutive qualifying runs are still required by the stricter PRD criterion.

## Repository Layout

```text
backend/                  FastAPI service, Pydantic models, SQLite store, tests
frontend/                 Vite TypeScript workbench
runtime/frontend-dist/    Ignored production frontend build served by FastAPI
scripts/                  Lifecycle scripts and model adapter scripts
tests/e2e/                Mock HTTP E2E contract and one-click lifecycle tests
model-manifest.lock.json  Pinned model sources, revisions, file sizes, hashes
docs/                     Architecture, deployment, competition, model docs
```

Runtime data is outside source by default:

```text
/home/Developer/overseaark-models  model weights
/home/Developer/overseaark-data    SQLite, uploads, artifacts, logs, pid files
```

## One-command Start

DGX Spark command mode:

```bash
./overseaark start
```

Developer/mock mode without GPU model assets:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark start
```

`start` is idempotent. It bootstraps missing dependencies, builds the frontend, installs the pinned native vLLM ARM64 CUDA wheel when needed, verifies locked model files, downloads only missing or invalid files, launches local vLLM on demand at `127.0.0.1:8011`, starts FastAPI, and waits for `/api/v1/health`.

Use these endpoints after startup:

- App: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/v1/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

Useful lifecycle commands:

```bash
./overseaark status
./overseaark logs all
./overseaark logs llm
./overseaark llm status
./overseaark llm stop
./overseaark stop
```

## Configuration

Copy `.env.example` only when the defaults need changing:

```bash
cp .env.example .env
```

Important defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OVERSEAARK_HOST` | `127.0.0.1` | Localhost-only bind. |
| `OVERSEAARK_BACKEND_PORT` | `8000` | FastAPI API and frontend. |
| `OVERSEAARK_MODELS_DIR` | `/home/Developer/overseaark-models` | External model cache. |
| `OVERSEAARK_DATA_DIR` | `/home/Developer/overseaark-data` | SQLite, uploads, artifacts, logs. |
| `OVERSEAARK_ADAPTER_MODE` | `command` | Real local adapters on DGX. |
| `OVERSEAARK_AUTO_BOOTSTRAP` | `1` | Repair missing dependencies during `start`. |
| `OVERSEAARK_AUTO_DOWNLOAD_MODELS` | `1` | Repair missing/corrupt locked models during `start`. |
| `OVERSEAARK_STEP1X_STEPS` | `6` | DGX-measured demo default; increase for final-production image refinement. |
| `OVERSEAARK_COSMOS_STEPS` | `28` | Default Cosmos3-Edge inference steps. |
| `OVERSEAARK_VLLM_ENV_DIR` | `.venv-vllm` | Isolated native vLLM environment. |
| `OVERSEAARK_VLLM_PORT` | `8011` | Local OpenAI-compatible Qwen endpoint. |
| `OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION` | `0.4` | DGX Spark vLLM memory budget. |
| `OVERSEAARK_VLLM_MAX_MODEL_LEN` | `262144` | DGX Spark context length for Qwen3.6. |

Mainland-network defaults use TUNA and mirrors while keeping locked hashes authoritative:

```bash
MODELSCOPE_ENDPOINT=https://modelscope.cn
HF_ENDPOINT=https://hf-mirror.com
OVERSEAARK_PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
OVERSEAARK_PYPI_FILE_PREFIX=https://pypi.tuna.tsinghua.edu.cn/packages/
OVERSEAARK_PYTORCH_INDEX=https://mirrors.aliyun.com/pytorch-wheels/cu130
OVERSEAARK_GITHUB_GIT_PREFIX=https://gh-proxy.com/https://github.com/
OVERSEAARK_GITHUB_ASSET_PREFIX=https://ghfast.top/
```

Set an empty mirror prefix to use upstream URLs directly.

## Model Stack

`model-manifest.lock.json` is the source of truth. Required locked files total 81,211,096,221 bytes. With optional Cosmos-Predict2 synced, the manifest totals 85,535,325,812 bytes. The primary Qwen NVFP4 model files total about 23.45 GB.

| Role | Manifest id | Source | Revision | Local directory | Required | License |
| --- | --- | --- | --- | --- | --- | --- |
| LLM/VLM | `qwen3.6-35b-a3b-nvfp4` | `nvidia/Qwen3.6-35B-A3B-NVFP4` from Hugging Face mirror | `491c2f1ea524c639598bf8fa787a93fed5a6fbce` | `nvidia/qwen3.6-35b-a3b-nvfp4` | yes | Apache-2.0 |
| Image | `step1x-edit-v1p2` | `stepfun-ai/Step1X-Edit-v1p2` from Hugging Face mirror | `ca85b97fd19f2235dc0d6fd3633d1319f169e149` | `stepfun/step1x-edit-v1p2` | yes | Apache-2.0 |
| Optional T2I | `cosmos-predict2-0.6b-text2image` | `nv-community/Cosmos-Predict2-0.6B-Text2Image` ModelScope mirror of NVIDIA upstream | `master`, upstream `dd55b6858b22ad569976bff207880b8fea839da7` | `nvidia/cosmos-predict2-0.6b-text2image` | no | NVIDIA Open Model License |
| Video | `cosmos3-edge` | `nv-community/Cosmos3-Edge` ModelScope mirror of NVIDIA upstream | `master`, upstream `6f58f6b4c91288838e60b6bcb2cc45d997e961de` | `nvidia/cosmos3-edge` | yes | NVIDIA Open Model Development Weight License 1.1 |
| Video VAE | `wan2.2-vae-cosmos3` | `Wan-AI/Wan2.2-TI2V-5B` from ModelScope | `master`, upstream `921dbaf3f1674a56f47e83fb80a34bac8a8f203e` | `wan/wan2.2-vae` | yes | Apache-2.0 |
| ASR | `nemotron-asr-streaming-0.6b` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | `f3d333391852ba876df169dcc9ba902d25b6ab0b` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | yes | NVIDIA Open Model Development Weight License 1.1 |
| TTS codec | `nemo-nano-codec-22khz-1.89kbps-21.5fps` | `nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps` | `3c482a402a3c4cf33690a2c0f0a7d41afea6bd6a` | `nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps` | yes | NVIDIA Open Model License |
| TTS | `magpie-tts-multilingual-357m` | `nvidia/magpie_tts_multilingual_357m` | `34d7e40da85cabc97f92198889b65cea27bc7fd1` | `nvidia/magpie_tts_multilingual_357m` | yes | NVIDIA Open Model License |
| TTS tokenizer | `byt5-small-tokenizer` | `google/byt5-small` | `68377bdc18a2ffec8a0533fef03b1c513a4dd49d` | `google/byt5-small` | yes | Apache-2.0 |

Pinned framework commits:

| Component | Commit |
| --- | --- |
| native vLLM ARM64 CUDA wheel | `vLLM 0.25.1`, wheel SHA-256 `bdffbe35b2c1ab8f2a9dcc337b657261d9b192c92c217e5a2f98a8835fe78daa` |
| Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| NVIDIA-NeMo/NeMo for ASR | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |
| NeMo TTS environment | `nemo_toolkit[tts]==2.7.3` |

## Pipeline

The backend runs one retry per stage:

1. `market_positioning`: Qwen3.6 produces positioning and market hypotheses.
2. `buyer_persona`: Qwen3.6 produces personas and decision triggers.
3. `multilingual_copy`: Qwen3.6 produces `zh`, `en`, and `ja` copy.
4. `visual_design`: Step1X generates `visual_design.png`; typography overlay is added after generation.
5. `media_production`: Magpie TTS generates `voice_<language>.wav`; Cosmos3-Edge generates 480p video from the poster; ffmpeg composes narration and subtitles.
6. `quality_packaging`: Nemotron ASR checks TTS round-trip similarity against threshold `0.75`; one TTS retry is attempted for a failing language; zip export is written.

`ModelManager` serializes all heavy calls. In command mode the vLLM server is stopped on demand before image, video, ASR, or TTS work so the GPU memory path stays single-active.

## API Examples

Health:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

Models:

```bash
curl -sS http://127.0.0.1:8000/api/v1/models
```

Transcribe audio:

```bash
curl -sS http://127.0.0.1:8000/api/v1/transcriptions \
  -F 'audio=@demo.wav;type=audio/wav' \
  -F 'language=auto'
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

Stream progress:

```bash
curl -N http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/events
```

Rerun from a stage:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/rerun/media_production
```

Cancel and export:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/cancel
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export
```

## Offline and Safety Boundary

- Runtime services bind to `127.0.0.1`.
- Production frontend assets are served by FastAPI on port `8000`; no `5173` tunnel is needed.
- `validate_offline_runtime` rejects non-local LLM base URLs and adapter commands containing remote URLs.
- Runtime inference sets `TRANSFORMERS_OFFLINE=1`, `HF_HUB_OFFLINE=1`, and `HF_DATASETS_OFFLINE=1`.
- Model acquisition is the only lifecycle step that temporarily disables offline Hugging Face flags.
- Model file verification rejects unsafe paths, size mismatches, SHA-256 mismatches, and cleanup outside the locked model root.
- Model weights are not committed to this repository.

SSH tunnel from a local machine:

```bash
ssh -p 6105 \
  -L 8000:127.0.0.1:8000 \
  root@106.13.186.155
```

## Verification

Local-safe verification:

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark doctor
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark models verify
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark test
```

Command-mode model verification:

```bash
./overseaark models verify
```

Direct adapter benchmarks with verified models:

```bash
./overseaark benchmark llm
./overseaark benchmark image
./overseaark benchmark audio
./overseaark benchmark video
```

`benchmark audio` runs three cycles across `zh`, `en`, and `ja`, uses two Magpie voices per language, checks both specified-language and automatic Nemotron ASR, and fails below similarity `0.75`.

## Competition Highlights

- Single monorepo with reproducible local operations.
- No Docker; the target path is native aarch64 Ubuntu 24.04 on DGX Spark.
- Pinned `nvidia/Qwen3.6-35B-A3B-NVFP4` served by native vLLM `0.25.1` from an isolated `.venv-vllm`, with no Docker runtime.
- vLLM listens only on localhost `127.0.0.1:8011` and uses the DGX Spark parameters from the lifecycle script: `--tensor-parallel-size 1`, `--kv-cache-dtype fp8`, `--attention-backend flashinfer`, `--moe-backend marlin`, `--max-model-len 262144`, `--max-num-seqs 4`, `--max-num-batched-tokens 8192`, chunked prefill, prefix caching, and MTP speculative decoding.
- Step1X defaults to 6 steps after a 176.3-second DGX image benchmark retained a usable product poster while saving about 45 seconds versus run 3.
- Cosmos3-Edge default is 28 steps and uses the pinned Wan2.2 VAE dependency.
- Nemotron ASR and Magpie TTS close the audio loop with measurable round-trip QC.
- Heavy model calls are serialized and the LLM server is released before other GPU adapters.
- Missing models and corrupt same-size locked files are repaired automatically by rerunning `./overseaark start`.
- Export manifests record model ids, revisions, local directories, licenses, stage attempts, and model calls.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `runtime dependencies are incomplete` | Bootstrap did not finish or a pinned venv is missing imports. | Rerun `./overseaark start`; caches are reused. Inspect `./overseaark logs all` if it repeats. |
| `Qwen3.6 NVFP4 is missing` | Required model file is absent from `OVERSEAARK_MODELS_DIR`. | Run `./overseaark start` or `./overseaark models sync`. |
| `model manifest verification` fails | Missing, truncated, or SHA-mismatched locked file. | Rerun `./overseaark start`; invalid locked files are removed and fetched again. |
| `pinned native vLLM is missing` | `.venv-vllm` is absent or does not contain the pinned CUDA ARM64 wheel. | Rerun `./overseaark bootstrap`; remove `.venv-vllm` first only when forcing a clean reinstall. |
| First vLLM start appears slow | FlashInfer is compiling and caching GB10/SM121 kernels. | Leave the first start running. JIT is intentionally serialized with `MAX_JOBS=1` to avoid unified-memory OOM; the verified cold-cache start took 526 seconds and later full restart took 166 seconds. Inspect `./overseaark logs llm` for progress. |
| Adapter timeout | A heavy model exceeded `OVERSEAARK_ADAPTER_TIMEOUT`. | Check `OVERSEAARK_ADAPTER_TIMEOUT`, model logs, and GPU memory pressure; the process group is terminated on timeout. |
| Frontend shows degraded local preview | Backend is unavailable from the browser. | Check `./overseaark status` and `http://127.0.0.1:8000/api/v1/health`. |
| Upload rejected with 415 | Unsupported content type or image bytes do not match the declared type. | Use real PNG/JPEG/WebP files for products and WAV/MP3/M4A/WebM for audio. |
| Export returns 409 | Campaign has not reached packaging and no partial export is available. | Wait for a terminal campaign status or inspect stage errors. |

## More Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Competition Notes](docs/COMPETITION.md)
- [Model Licenses](docs/MODEL_LICENSES.md)
- [PRD v1.1](docs/PRD-v1.1.md)
