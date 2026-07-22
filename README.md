# DGX Spark一支不下班的本地多模态外贸营销团队

OverseaArk is a local-first multimodal campaign workbench for cross-border sellers on NVIDIA DGX Spark. The repository is a single monorepo: FastAPI backend, Vite TypeScript frontend, local model adapters, lifecycle scripts, tests, and the pinned model manifest all live here. There is no Docker path and no cloud inference path.

The implemented demo flow accepts one product image and product description, runs six serialized stages, exposes each stage's process artifacts as soon as they are persisted, and exports either a complete multilingual ZIP or a ZIP scoped to the currently selected output language.

The web workbench includes a **Fill demo / 一键填入示例** action. It loads a repository-owned product image and complete localized product brief into the existing upload and campaign form, so a live demonstration only needs one review click followed by **Create campaign / 创建活动**.

## Current Status

- Implemented: root one-command lifecycle, FastAPI API, built frontend mounted by FastAPI, SQLite campaign/event store, multipart uploads, six campaign stages, resumable SSE progress, localized and per-stage artifact previews, rerun, cancel, complete/per-language export, a Simplified Chinese default UI with a persistent English switch, one-click demo input, mock mode, command adapter mode, model verification/sync, native vLLM LLM runtime, resident ASR/TTS workers, and process-group cleanup for timed-out adapters.
- Implemented command adapters: Qwen3.6 LLM/VLM through localhost native vLLM, Step1X image generation, Cosmos3-Edge video generation, Nemotron ASR, and Magpie TTS.
- Implemented safety boundary: localhost-only serving, no remote model command URLs, offline Hugging Face runtime flags, serialized inference calls, and a safe-warm model policy that keeps ASR/TTS ready while loading the larger visual runtime only when needed.
- Not implemented: Docker, ComfyUI, OpenClaw, Ollama, StepFun cloud APIs, NVIDIA hosted inference APIs, or public service binding.
- DGX E2E evidence: native vLLM run 9 completed all six stages on first attempts in `580.147s` (9m40s). It produced a real 854x480 H.264/AAC Cosmos video, a valid 23-member ZIP, and ASR similarities zh `0.9375`, en `1.0`, ja `0.9189`. Run 8 is retained as truthful negative evidence: its Chinese mixed-script `GaN` narration stayed below `0.75` and the campaign remained `partial`, which led to the speech-native prompt fix used by run 9. This establishes one qualifying native vLLM run; three consecutive qualifying runs are still required by the stricter PRD criterion.

## 项目报告书

### 项目概述、目标与背景

出海方舟 OverseaArk 是面向中小外贸企业、跨境卖家和代运营团队的本地多模态营销工作台。传统外贸素材制作通常分散在市场调研、翻译、海报、配音、视频和质检等多个工具中，产品图、工艺信息与未发布卖点还可能在不同云服务之间流转。项目的目标是在一台 NVIDIA DGX Spark 上把这些步骤收敛成可重复、可恢复、可审计的本地流水线：用户只需提交一张产品图和产品描述，系统便生成中英日文案、产品海报、三语配音、480p 短视频、质量报告和完整 ZIP。服务只监听 localhost，推理阶段关闭 Hugging Face 与 Transformers 在线访问，不把产品资料发送到云端模型。

### 作品介绍与核心亮点

产品把交付流程固定为市场定位、买家画像、多语文案、视觉设计、音视频制作、质量与打包六个阶段。前端默认显示简体中文，可一键切换为 English，并把界面语言保存在浏览器中；“一键填入示例”会补齐商品图、描述、目标市场和中英日输出选项。运行时通过 SSE 显示递增事件序号，刷新页面后可以恢复；每个已持久化的阶段结果会立即出现在“阶段过程产物”中，海报、语音、视频和质检可直接预览。后端把 Campaign、Stage、重试和产物记录在 SQLite 与本地目录中。单阶段失败会自动重试一次，第二次仍失败则如实标记为 `partial`，同时保留此前成功产物。Cosmos 失败时可以生成明确标记的降级视频，但不会冒充真模型结果。完整 ZIP 按 `shared/` 和该 Campaign 所请求的 `zh/`、`en/`、`ja/` 语言目录组织，也可只导出当前语言；清单记录模型 ID、revision、许可证、阶段尝试次数和调用记录。

核心体验是一键脚本。`./overseaark start` 会自动检查系统、补齐 Python/Node 依赖、构建前端、安装隔离的 native vLLM 环境、校验模型清单、删除损坏分片、断点下载缺失文件、启动本地服务并等待健康检查。它不依赖 Docker、ComfyUI 或云端推理控制台；运维、日志、模型同步、诊断、测试和 benchmark 都由同一个根命令管理。模型和用户数据分别保存在仓库外的 `/home/Developer/overseaark-models` 与 `/home/Developer/overseaark-data`，代码仓库不会混入权重、数据库、凭据或生成素材。

### 技术方案、架构与创新点

后端采用 FastAPI、Pydantic、SQLite 和本地文件系统，前端采用 Vite、TypeScript 和 SSE。Qwen3.6、Step1X、Cosmos、Magpie 与 Nemotron 都通过显式 adapter 接口接入，`ModelManager` 用单一异步锁串行推理调用。默认的 safe-warm 策略让 Nemotron ASR 与 Magpie TTS 常驻，在活动间隔预热 vLLM，进入 Step1X/Cosmos 视觉阶段前释放 vLLM；Step1X 只在实测统一内存余量足够时才可选常驻，Cosmos 始终按需启动。每个非常驻命令 adapter 运行在独立进程组中，超时或取消会终止完整进程组，防止残留 CUDA context。上传不仅检查 MIME，还检查图片和音频容器签名；导出前会解析真实路径并拒绝符号链接越界，从而阻止恶意 adapter 把 Campaign 目录外的文件打进 ZIP。

技术创新不只在模型组合，而在“生成—回听—判定—保留证据”的闭环。MagpieTTS 生成中英日音频后，Nemotron ASR 重新转写并计算规范化相似度；低于 `0.75` 时只重做失败语言。Run8 因中文口播中的拉丁缩写而被如实保留为 `partial`，随后生成规则改为使用可直接发音的本地语言，Run9 三种语言均一次通过。这种失败可见、产物可追溯的设计比隐藏错误或静默切换模型更适合真实业务和赛事复现。

### NVIDIA 与 StepFun 技术栈

主模型为 NVIDIA 优化的 `nvidia/Qwen3.6-35B-A3B-NVFP4`，固定 revision 后由 native vLLM 0.25.1 在 `127.0.0.1:8011` 提供 OpenAI-compatible 接口。运行时启用 FP8 KV cache、FlashInfer attention、Marlin MoE、chunked prefill、prefix caching 和 MTP speculative decoding。视觉编辑使用 StepFun `Step1X-Edit-v1p2` FP8 权重；图生视频使用 NVIDIA Cosmos3-Edge 与 Cosmos Framework；语音识别使用 NVIDIA Nemotron 3.5 ASR Streaming 0.6B；语音合成使用 NVIDIA NeMo MagpieTTS Multilingual 357M 和 Nano Codec。所有 CUDA 重任务都在 DGX Spark 本地执行，ffmpeg 只负责字幕、音频和 MP4 封装。

### 实机结果与优化过程

native vLLM Run9 六阶段全部一次成功，端到端用时 `580.147s`。该轮输出 15 秒、854×480、H.264/AAC 的真实 Cosmos 视频和 23 文件 ZIP；中、英、日 TTS 回听相似度分别为 `0.9375`、`1.0`、`0.9189`。优化过程包括把 Step1X 演示默认值从 8 步调整到经独立基准验证的 6 步、将 FlashInfer 首次 JIT 编译并行度限制为 1 以避免统一内存 OOM、让中文和日文视频脚本避免不可直接发音的拉丁缩写，以及在视觉阶段前卸载 vLLM。完整本地回归由 `./overseaark test` 统一执行后端、前端、生命周期、HTTP Mock E2E 和安全用例；具体用例数以当次测试输出为准。

### 团队分工与贡献

公开仓库按职责记录贡献，不在源代码中披露成员住址、照片等个人信息：产品与内容职责负责 PRD、六阶段交付合同和赛事报告；前端职责负责 Campaign 创建、SSE 进度、恢复、重跑和导出体验；后端职责负责 API、状态机、SQLite、ModelManager 与安全边界；模型工程职责负责 vLLM、Step1X、Cosmos、Nemotron、Magpie 的 DGX Spark 适配和模型清单；质量与交付职责负责 UltraQA 对抗场景、实机 E2E、OBS 演示录制、CapCut CLI 剪辑和公开文档。真实团队名称、成员名单和合影仅在赛事提交表中填写，避免把个人资料永久写入公开 Git 历史。

### 未来展望

下一步首先补齐两轮连续的 native vLLM 十分钟内实测，满足 PRD 的三轮严格验收；同时持续验证 ASR/TTS 常驻进程在连续活动中的内存稳定性，并只在 119 GiB 统一内存余量充分时评估 Step1X 常驻。产品层面会加入可编辑品牌模板、人工审核节点、Campaign 对比和离线素材版本管理；工程层面会继续压缩冷启动、增加模型缓存可视化和内核级离线网络审计。所有扩展仍会坚持 localhost、显式模型版本、失败不伪装和用户数据可完全删除的原则。

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

`start` is idempotent. It bootstraps missing dependencies, builds the frontend, installs the pinned native vLLM ARM64 CUDA wheel when needed, verifies locked model files, downloads only missing or invalid files, starts local vLLM at `127.0.0.1:8011`, starts FastAPI, and waits for `/api/v1/health`. ASR/TTS warmup then continues in the backend without making the site unavailable; inspect `model_status` in `/api/v1/health` and `residency.warmup` in `/api/v1/models` for `warming`, `ready`, or `degraded`.

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

### GPU usage

Run these commands in the DGX Spark SSH terminal while a campaign is active:

```bash
# One-time snapshot
nvidia-smi

# Live utilization, power, clocks, temperature, and PCIe activity
nvidia-smi dmon -s pucvmet
```

The web page also has an expandable **在哪里查看 GPU 使用情况？ / Where can I view GPU usage?** guide with these commands. It is an operator guide, not an embedded metrics dashboard: the live numbers remain in the SSH terminal.

When the background monitor used for the live demo is running, its output is available at:

```bash
tail -f /home/Developer/overseaark-data/logs/gpu-dmon.log
```

DGX Spark uses unified CPU/GPU memory. Some per-process memory columns can therefore appear as `N/A` or `Not Supported` in `nvidia-smi`; use `free -h` alongside it to inspect total unified-memory pressure.

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

Set an empty mirror prefix to use upstream URLs directly.

## Model Stack

`model-manifest.lock.json` is the source of truth. Required locked files total 81,211,096,221 bytes (about 75.6 GiB). With optional Cosmos-Predict2 synced, the manifest totals 85,535,325,812 bytes. The primary Qwen NVFP4 model files total about 23.45 GB.

Do not interpret the 119 GiB unified memory shown by the DGX Spark as room to keep every model loaded simultaneously. The required raw model files alone total about 75.6 GiB, before accounting for vLLM KV cache, CUDA contexts, decoded weights, Step1X/Cosmos activations, video buffers, the OS, and filesystem cache. Those runtime allocations are workload-dependent and can overlap during a transition, so an all-resident profile has little safe OOM margin. The supported default is **safe-warm**: ASR/TTS resident, Step1X optional resident after measurement, vLLM prewarmed between campaigns but released before visual stages, and Cosmos loaded on demand.

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

`ModelManager` serializes inference calls. In the default command-mode profile, Nemotron ASR and Magpie TTS are long-lived JSONL workers, vLLM is ready for the three LLM stages and is released before Step1X/Cosmos work, and Cosmos remains an on-demand process. When the campaign reaches a terminal state, the backend prepares the idle profile again for the next campaign. `GET /api/v1/models` reports the selected policy and resident-worker status; `all_models_resident` intentionally remains `false`.

The frontend separates two views of the output:

- **Localized outputs / 本地化输出** shows only the selected `zh`, `en`, or `ja` copy and narration.
- **Stage artifacts / 阶段过程产物** groups every available intermediate result by the six pipeline stages. Structured text, poster, audio, video, and QC artifacts appear as soon as the backend persists them, including while a later stage is still running.

The complete export uses language and shared folders (legacy compatibility entries are also retained):

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

Only folders for languages requested by that campaign are present.

A single-language export includes only that campaign language's copy/audio and language-safe metadata. A video is included only when its narration language matches the requested export language.

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

Valid asset keys are `source`, `poster`, `video`, `qc`, `audio-zh`, `audio-en`, and `audio-ja`; an asset is available only after its producing stage has succeeded.

Cancel and export:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/cancel
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export
curl -OJ 'http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export?language=en'
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

1. Open `http://127.0.0.1:8000`; confirm Simplified Chinese is the default and switch to **English**, then refresh to confirm persistence.
2. Select **一键填入示例 / Fill demo**; confirm the image and complete form are filled, then create the campaign.
3. While it runs, confirm SSE progress advances and completed-stage results appear under **阶段过程产物 / Stage artifacts** before the whole campaign finishes.
4. Switch the output tabs between Chinese, English, and Japanese; confirm the localized copy/audio follows the selected language.
5. After `completed` or `partial`, download both **all languages** and the current-language ZIP and inspect their folder boundaries.
6. Run `nvidia-smi dmon -s pucvmet` in the SSH terminal during the heavy stages and `free -h` between stage transitions.

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
- [PRD v1.1](docs/PRD-v1.1.md)
