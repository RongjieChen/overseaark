# DGX Spark: A Local Multimodal Marketing Team That Never Clocks Out

[中文](README.md)

OverseaArk is a local-first multimodal campaign workbench for exporters, cross-border sellers, and agency teams on NVIDIA DGX Spark. The repository is a single monorepo: FastAPI backend, Vite TypeScript frontend, local model adapters, lifecycle scripts, tests, and the pinned model manifest all live here. The current implementation has no Docker path and no cloud inference path.

The demo flow accepts one product image and a product description. It runs six serialized stages to produce market positioning, buyer personas, Chinese/English/Japanese copy, a product poster, trilingual voiceovers, a 480p short video, a quality report, and ZIP packages. Each stage artifact appears as soon as it is persisted. Users can export either a complete multilingual ZIP or a ZIP scoped to the currently selected output language.

The web workbench includes **Fill demo / 一键填入示例**. It loads a repository-owned product image and a complete localized product brief into the existing upload and campaign form, so a live demo only needs one review click followed by **Create campaign / 创建活动**.

## Current Status

- Implemented: root one-command lifecycle, FastAPI API, built frontend mounted by FastAPI, SQLite campaign/event store, multipart uploads, six campaign stages, resumable SSE progress, localized and per-stage artifact previews, rerun, cancel, complete/per-language export, Simplified Chinese default UI with a persistent English switch, frontend i18n, one-click demo input, mock mode, command adapter mode, model verification/sync, native vLLM LLM runtime, resident ASR/TTS workers, and process-group cleanup for timed-out adapters.
- Implemented command adapters: Qwen3.6 LLM/VLM through localhost native vLLM, Step1X image generation, Cosmos3-Edge video generation, Nemotron ASR, and Magpie TTS.
- Implemented safety boundary: localhost-only serving, no remote model command URLs, offline Hugging Face runtime flags, serialized inference calls, and a safe-warm model policy that keeps ASR/TTS ready while loading the larger visual runtime only when needed.
- DGX E2E evidence: native vLLM Run9 completed all six stages on first attempts in `580.147s` (9m40s). The deployed safe-warm build then completed UQ-14 campaign `95e8efa8-7dbd-4285-b05a-8db54429d340` in `451.296s` (7m31s), again with every stage succeeding on its first attempt. Its zh/en/ja ASR similarities were `0.8333`/`1.0`/`0.88`; the complete ZIP and three scoped ZIPs passed integrity and language-isolation checks. UQ-15 cancelled a real active TTS request, terminated the old TTS worker, and automatically restored it with a new PID and incremented start count. Run8 remains truthful negative evidence for the mixed-script narration defect. The stricter criterion for three consecutive qualifying current-build runs remains open.

## DGX Spark Quick Start

### 1. Start real local model mode

```bash
./overseaark start
```

`start` is idempotent. It checks the system, repairs Python/Node dependencies, builds the frontend, installs the pinned native vLLM ARM64 CUDA wheel, verifies locked model files, deletes corrupt shards, resumes downloads for missing files, starts local vLLM at `127.0.0.1:8011`, starts FastAPI, and waits for `/api/v1/health`. ASR/TTS warmup then continues asynchronously inside the backend without making the web app unavailable.

After startup, use:

- App: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/v1/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

Inspect model warmup state:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
curl -sS http://127.0.0.1:8000/api/v1/models
```

`model_status` in `/api/v1/health` and `residency.warmup` in `/api/v1/models` report `pending`, `warming`, `ready`, `degraded`, or `cancelled`.

### 2. Developer mock mode without GPU/model assets

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark start
```

Use this mode for local development and HTTP contract rehearsal. It does not download or load the large model assets.

### 3. Useful lifecycle commands

```bash
./overseaark status
./overseaark logs all
./overseaark logs llm
./overseaark llm status
./overseaark llm stop
./overseaark stop
```

## Repository Layout

```text
backend/                  FastAPI service, Pydantic models, SQLite store, backend tests
frontend/                 Vite TypeScript workbench
runtime/frontend-dist/    Ignored production frontend build served by FastAPI
scripts/                  Lifecycle scripts and model adapter scripts
tests/e2e/                Mock HTTP E2E contract and one-click lifecycle tests
model-manifest.lock.json  Pinned model sources, revisions, file sizes, hashes
docs/                     Architecture, deployment, competition, and model docs
```

Runtime data is outside source by default:

```text
/home/Developer/overseaark-models  model weights
/home/Developer/overseaark-data    SQLite, uploads, artifacts, logs, pid files
```

Do not commit model weights or user data to this repository.

## Project Report

### Overview, Goal, and Background

Cross-border marketing work is often split across market research, translation, posters, voiceover, video, and quality-check tools. Product images, manufacturing details, and unpublished selling points can also move through multiple cloud services. OverseaArk is designed to collapse those steps into a repeatable, recoverable, auditable local pipeline on one DGX Spark. A user submits a product image and description, and the system produces Chinese/English/Japanese marketing assets plus an auditable archive. Services listen only on localhost, Hugging Face and Transformers online access is disabled during inference, and product data is not sent to cloud models.

### Core Experience

The pipeline has six fixed stages:

1. `market_positioning`: Qwen3.6 produces positioning and market hypotheses.
2. `buyer_persona`: Qwen3.6 produces personas and decision triggers.
3. `multilingual_copy`: Qwen3.6 produces `zh`, `en`, and `ja` copy.
4. `visual_design`: Step1X generates `visual_design.png`; typography overlay is added after generation.
5. `media_production`: Magpie TTS generates `voice_<language>.wav`; Cosmos3-Edge generates 480p video from the poster; ffmpeg composes narration, subtitles, and MP4 output.
6. `quality_packaging`: Nemotron ASR checks the TTS round trip against similarity threshold `0.75`; a failing language gets one TTS retry; the ZIP export is then written.

The frontend defaults to Simplified Chinese, can switch to English, and stores the language choice in the browser. During a campaign, SSE shows incrementing event sequence numbers and can recover after refresh. **Localized outputs / 本地化输出** shows only the currently selected language's copy and voiceover, while **Stage artifacts / 阶段过程产物** groups every persisted intermediate result by the six pipeline stages. A stage is retried once after failure; if it fails again, the campaign is truthfully marked `partial` and earlier successful artifacts remain available. Cosmos failures can produce a clearly labeled degraded video, but the system does not present that as a true model success.

### Technical Design

The backend uses FastAPI, Pydantic, SQLite, and the local filesystem. The frontend uses Vite, TypeScript, and SSE. Qwen3.6, Step1X, Cosmos, Magpie, and Nemotron connect through explicit adapter interfaces, and `ModelManager` serializes inference with one async lock.

The default safe-warm policy is:

- Nemotron ASR and Magpie TTS stay resident.
- vLLM is prewarmed between campaigns and released before Step1X/Cosmos visual stages.
- Step1X residency is opt-in only after measuring unified-memory headroom.
- Cosmos always starts on demand.
- Each non-resident command adapter runs in its own process group, and timeout or cancellation terminates the full group to avoid leftover CUDA contexts.

Uploads are validated by MIME type and by image/audio container signature. Export resolves real paths and rejects symlink escapes before adding files to ZIPs, preventing a malicious adapter from packaging files outside the campaign directory.

### NVIDIA and StepFun Stack

The primary model is NVIDIA-optimized `nvidia/Qwen3.6-35B-A3B-NVFP4`, pinned by revision and served by native vLLM `0.25.1` at `127.0.0.1:8011` through an OpenAI-compatible interface. Runtime flags enable FP8 KV cache, FlashInfer attention, Marlin MoE, chunked prefill, prefix caching, and MTP speculative decoding.

Image editing uses StepFun `Step1X-Edit-v1p2` FP8 weights. Image-to-video uses NVIDIA Cosmos3-Edge with Cosmos Framework. Speech recognition uses NVIDIA Nemotron 3.5 ASR Streaming 0.6B. Speech synthesis uses NVIDIA NeMo MagpieTTS Multilingual 357M and Nano Codec. All CUDA-heavy work runs locally on DGX Spark; ffmpeg is used only for subtitles, audio, and MP4 packaging.

### Real DGX Results and Optimization

Native vLLM Run9 completed all six stages on first attempts in `580.147s`. After deploying the safe-warm build, UQ-14 completed a real campaign in `451.296s`, again with all six stages passing on first attempts. Chinese, English, and Japanese TTS round-trip similarities were `0.8333`, `1.0`, and `0.88`; the complete ZIP and three single-language ZIPs passed integrity and language-isolation checks.

UQ-15 reran from the media stage and cancelled during a real TTS request. The old TTS PID was terminated, a new worker recovered automatically, start count increased from `1` to `2`, the ASR process was unchanged, and the service showed no OOM or CUDA errors. Optimization work included lowering the Step1X demo default from 8 steps to a separately benchmarked 6 steps, serializing first-run FlashInfer JIT with `MAX_JOBS=1` to avoid unified-memory OOM, avoiding Latin abbreviations in Chinese/Japanese video narration, and unloading vLLM before visual stages. The local regression command `./overseaark test` runs backend, frontend, lifecycle, HTTP Mock E2E, and safety cases; use the current command output for exact test counts.

### Team Roles

- Captain Chen Rongjie is responsible for project and technical implementation.
- Team member Chen Zhengchao is responsible for product and design.
- Team member Huang Dongmei is responsible for end-to-end quality control.

### Roadmap

The next acceptance step is to collect three consecutive native vLLM runs under ten minutes on the same current build, satisfying the stricter PRD criterion. The project should also keep validating ASR/TTS resident-worker memory stability across consecutive campaigns and evaluate Step1X residency only when the 119 GiB unified-memory headroom is sufficient. Product work can add editable brand templates, human review gates, campaign comparison, and offline asset versioning. Engineering work can continue reducing cold start, exposing model-cache state, and adding kernel-level offline network auditing. Future work should keep the same localhost, explicit model-version, truthful-failure, and removable-user-data principles.

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
| `OVERSEAARK_AUTO_DOWNLOAD_MODELS` | `1` | Repair missing or corrupt locked models during `start`. |
| `OVERSEAARK_RESIDENT_ADAPTERS` | `asr,tts` | Comma-separated resident workers; optionally add `image` only after checking memory headroom. |
| `OVERSEAARK_KEEP_VLLM_RESIDENT` | `0` | Keep disabled for the safe profile; vLLM is prewarmed between campaigns and released before visual work. |
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

Set a mirror prefix to an empty string to use upstream URLs directly.

## Model Stack

`model-manifest.lock.json` is the source of truth for model provenance and file verification. Required locked files total 81,211,096,221 bytes (about 75.6 GiB). With optional Cosmos-Predict2 synced, the manifest totals 85,535,325,812 bytes. The primary Qwen NVFP4 model files total about 23.45 GB.

Do not interpret the 119 GiB unified memory shown by DGX Spark as room to keep every model loaded simultaneously. Required raw model files alone total about 75.6 GiB, before vLLM KV cache, CUDA contexts, decoded weights, Step1X/Cosmos activations, video buffers, the OS, and filesystem cache. The supported default is **safe-warm**: ASR/TTS resident, Step1X optional resident after measurement, vLLM prewarmed between campaigns but released before visual stages, and Cosmos loaded on demand.

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

## Export Layout

The complete export uses language and shared folders, with legacy compatibility entries retained:

```text
manifest.json
qc_report.json
shared/
  source_image.*
  poster.png
  video.mp4              # when a valid composed video exists
zh/
  copy.json
  audio.wav
en/
  copy.json
  audio.wav
ja/
  copy.json
  audio.wav
```

Only folders for languages requested by that campaign are present. A single-language export includes only that language's copy, audio, and language-safe metadata. Video is included only when its narration language matches the requested export language.

The export manifest records model ids, revisions, local directories, licenses, stage attempts, and model calls.

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

Preview persisted media and QC artifacts:

```bash
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/poster
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/audio-en
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/video
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/qc
```

Valid asset keys are `source`, `poster`, `video`, `qc`, `audio-zh`, `audio-en`, and `audio-ja`. An asset is available only after its producing stage has succeeded.

Cancel and export:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/cancel
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export
curl -OJ 'http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export?language=en'
```

## GPU Monitoring

Run these commands in the DGX Spark SSH terminal while a campaign is active:

```bash
# One-time snapshot
nvidia-smi

# Live utilization, power, clocks, temperature, and PCIe activity
nvidia-smi dmon -s pucvmet
```

The web page also has an expandable **在哪里查看 GPU 使用情况？ / Where can I view GPU usage?** guide. It is an operator guide, not an embedded metrics dashboard; live numbers remain in the SSH terminal.

When the background monitor used for the live demo is running, its output is available at:

```bash
tail -f /home/Developer/overseaark-data/logs/gpu-dmon.log
```

DGX Spark uses unified CPU/GPU memory. Some per-process memory columns can appear as `N/A` or `Not Supported` in `nvidia-smi`. Use this command alongside it to inspect total unified-memory pressure:

```bash
free -h
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

`./overseaark test` runs the backend suite, frontend type/build checks, lifecycle adversarial checks, backend smoke tests, and Mock HTTP E2E. Test counts change as coverage grows; use the totals printed by the current run rather than a number copied into documentation.

Manual browser smoke test after `start`:

1. Open `http://127.0.0.1:8000`; confirm Simplified Chinese is the default, switch to **English**, then refresh to confirm persistence.
2. Select **一键填入示例 / Fill demo**; confirm the image and complete form are filled, then create the campaign.
3. While it runs, confirm SSE progress advances and completed-stage results appear under **阶段过程产物 / Stage artifacts** before the whole campaign finishes.
4. Switch the output tabs between Chinese, English, and Japanese; confirm the localized copy/audio follows the selected language.
5. After `completed` or `partial`, download both **all languages** and the current-language ZIP and inspect their folder boundaries.
6. Run `nvidia-smi dmon -s pucvmet` in the SSH terminal during heavy stages and `free -h` between stage transitions.

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
- Inference calls are serialized; ASR/TTS workers stay ready, vLLM is prewarmed between campaigns and released before visual stages, Step1X residency is opt-in, and Cosmos remains on demand.
- Six-stage process artifacts are visible during execution, while the localized view and single-language export keep `zh`, `en`, and `ja` content separated.
- Missing models and corrupt same-size locked files are repaired automatically by rerunning `./overseaark start`.
- Export manifests record model ids, revisions, licenses, stage attempts, and model calls.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `runtime dependencies are incomplete` | Bootstrap did not finish or a pinned venv is missing imports. | Rerun `./overseaark start`; caches are reused. Inspect `./overseaark logs all` if it repeats. |
| `Qwen3.6 NVFP4 is missing` | Required model file is absent from `OVERSEAARK_MODELS_DIR`. | Run `./overseaark start` or `./overseaark models sync`. |
| `model manifest verification` fails | Missing, truncated, or SHA-mismatched locked file. | Rerun `./overseaark start`; invalid locked files are removed and fetched again. |
| `pinned native vLLM is missing` | `.venv-vllm` is absent or does not contain the pinned CUDA ARM64 wheel. | Rerun `./overseaark bootstrap`; remove `.venv-vllm` first only when forcing a clean reinstall. |
| First vLLM start appears slow | FlashInfer is compiling and caching GB10/SM121 kernels. | Leave the first start running. JIT is intentionally serialized with `MAX_JOBS=1` to avoid unified-memory OOM; the verified cold-cache start took 526 seconds and later full restart took 166 seconds. Inspect `./overseaark logs llm` for progress. |
| Adapter timeout | A heavy model exceeded `OVERSEAARK_ADAPTER_TIMEOUT`. | Check `OVERSEAARK_ADAPTER_TIMEOUT`, model logs, and GPU memory pressure; the process group is terminated on timeout. |
| Resident startup fails or memory pressure grows | The selected warm profile is too aggressive for current unified-memory headroom. | Restore `OVERSEAARK_RESIDENT_ADAPTERS=asr,tts` and `OVERSEAARK_KEEP_VLLM_RESIDENT=0`, restart, then inspect `free -h` and `/api/v1/models`. |
| `export?language=...` returns 422 | The code is unsupported or was not requested for this campaign. | Use `zh`, `en`, or `ja`, and only a language included when the campaign was created. |
| Frontend shows degraded local preview | Backend is unavailable from the browser. | Check `./overseaark status` and `http://127.0.0.1:8000/api/v1/health`. |
| Upload rejected with 415 | Unsupported content type or image bytes do not match the declared type. | Use real PNG/JPEG/WebP files for products and WAV/MP3/M4A/WebM for audio. |
| Export returns 409 | Campaign has not reached packaging and no partial export is available. | Wait for a terminal campaign status or inspect stage errors. |

## More Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Competition Notes](docs/COMPETITION.md)
- [Model Licenses](docs/MODEL_LICENSES.md)
- [PRD v2.0 (Markdown)](docs/PRD-v2.0.md)
- [PRD v2.0 (Word)](docs/出海方舟OverseaArk-PRD-v2.0.docx)
