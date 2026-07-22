# DGX Spark一支不下班的本地多模态外贸营销团队

[English](README.en.md)

出海方舟 OverseaArk 是面向外贸企业、跨境卖家和代运营团队的本地优先多模态营销工作台。项目运行目标是 NVIDIA DGX Spark：FastAPI 后端、Vite TypeScript 前端、本地模型 adapter、生命周期脚本、测试和固定模型清单都在同一个仓库中。当前实现没有 Docker 路径，也没有云端推理路径。

演示流程只需要一张商品图和一段商品描述。系统按六个串行阶段生成市场定位、买家画像、中英日文案、产品海报、三语配音、480p 短视频、质量报告和 ZIP 交付包。每个阶段的过程产物一旦持久化就会出现在页面中；最终可导出完整多语言 ZIP，也可导出当前语言的单语言 ZIP。

网页工作台提供 **一键填入示例 / Fill demo**。它会把仓库内置商品图和完整本地化商品简报填入上传区和 Campaign 表单，现场演示时只需检查内容并点击 **创建活动 / Create campaign**。

## 当前状态

- 已实现：根目录一键生命周期命令、FastAPI API、由 FastAPI 挂载的构建后前端、SQLite Campaign/Event 存储、multipart 上传、六阶段流水线、可恢复 SSE 进度、本地化输出和阶段产物预览、重跑、取消、完整/单语言导出、默认简体中文界面和持久 English 切换、前端 i18n、一键示例输入、mock 模式、command adapter 模式、模型校验/同步、native vLLM LLM 运行时、常驻 ASR/TTS worker，以及超时 adapter 的进程组清理。
- 已实现 command adapter：Qwen3.6 LLM/VLM 通过 localhost native vLLM 调用，Step1X 生成图片，Cosmos3-Edge 生成视频，Nemotron ASR 做语音识别，Magpie TTS 做语音合成。
- 已实现安全边界：只监听 localhost，不接受远程模型命令 URL，推理运行时设置 Hugging Face 离线标志，模型调用串行化，采用 safe-warm 策略让 ASR/TTS 保持就绪，并仅在需要时加载更大的视觉运行时。
- DGX E2E 证据：native vLLM Run9 六阶段全部一次成功，用时 `580.147s`（9m40s）。部署 safe-warm 版本后，UQ-14 Campaign `95e8efa8-7dbd-4285-b05a-8db54429d340` 用时 `451.296s`（7m31s），六阶段同样全部一次成功；中/英/日 ASR 相似度为 `0.8333`/`1.0`/`0.88`，完整 ZIP 和三个单语言 ZIP 通过完整性与语言隔离检查。UQ-15 在真实 TTS 执行中取消任务，旧 TTS worker 被终止，随后以新 PID 自动恢复且启动计数递增。Run8 仍作为混合脚本口播缺陷的真实负面证据保留。当前构建下“三轮连续合格运行”的更严格验收标准仍未完成。

## DGX Spark 快速启动

### 1. 启动真实本地模型模式

```bash
./overseaark start
```

`start` 是幂等命令。它会检查系统、补齐 Python/Node 依赖、构建前端、安装固定 native vLLM ARM64 CUDA wheel、校验锁定模型文件、删除损坏分片、断点下载缺失文件、在 `127.0.0.1:8011` 启动本地 vLLM、启动 FastAPI，并等待 `/api/v1/health` 健康检查。ASR/TTS 预热随后在后端异步继续，不会阻塞网页可用性。

启动后访问：

- 应用：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`
- OpenAPI：`http://127.0.0.1:8000/docs`

查看模型预热状态：

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
curl -sS http://127.0.0.1:8000/api/v1/models
```

`/api/v1/health` 中的 `model_status` 和 `/api/v1/models` 中的 `residency.warmup` 会显示 `pending`、`warming`、`ready`、`degraded` 或 `cancelled`。

### 2. 无 GPU/无模型的开发 mock 模式

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark start
```

这个模式用于本地开发和 HTTP 契约演练，不下载或加载大模型。

### 3. 常用生命周期命令

```bash
./overseaark status
./overseaark logs all
./overseaark logs llm
./overseaark llm status
./overseaark llm stop
./overseaark stop
```

## 仓库结构

```text
backend/                  FastAPI 服务、Pydantic 模型、SQLite 存储和后端测试
frontend/                 Vite TypeScript 工作台
runtime/frontend-dist/    被 git 忽略的前端生产构建，由 FastAPI 提供
scripts/                  生命周期脚本和模型 adapter 脚本
tests/e2e/                Mock HTTP E2E 契约和一键生命周期测试
model-manifest.lock.json  固定模型来源、revision、文件大小和哈希
docs/                     架构、部署、赛事和模型文档
```

默认运行时数据保存在仓库外：

```text
/home/Developer/overseaark-models  模型权重
/home/Developer/overseaark-data    SQLite、上传文件、产物、日志和 pid 文件
```

模型和用户数据不应提交到代码仓库。

## 项目报告

### 项目概述、目标与背景

外贸营销素材制作通常分散在市场调研、翻译、海报、配音、视频和质检等工具中，产品图、工艺信息和未发布卖点还可能在不同云服务之间流转。OverseaArk 的目标是在一台 DGX Spark 上把这些步骤收敛为可重复、可恢复、可审计的本地流水线：用户提交一张产品图和描述后，系统生成中英日交付素材和完整归档包。服务只监听 localhost，推理阶段关闭 Hugging Face 与 Transformers 在线访问，不把产品资料发送到云端模型。

### 核心体验

流水线固定为六个阶段：

1. `market_positioning`：Qwen3.6 生成市场定位和卖点假设。
2. `buyer_persona`：Qwen3.6 生成买家画像和决策触发点。
3. `multilingual_copy`：Qwen3.6 生成 `zh`、`en`、`ja` 文案。
4. `visual_design`：Step1X 生成 `visual_design.png`，生成后叠加排版。
5. `media_production`：Magpie TTS 生成 `voice_<language>.wav`；Cosmos3-Edge 从海报生成 480p 视频；ffmpeg 合成配音、字幕和 MP4。
6. `quality_packaging`：Nemotron ASR 回听 TTS，按 `0.75` 相似度阈值质检；失败语言会重试一次 TTS；随后写出 ZIP。

前端默认显示简体中文，可切换到 English，并把界面语言保存在浏览器中。Campaign 运行时通过 SSE 显示递增事件序号，刷新后可以恢复；“本地化输出”只显示当前选择语言的文案和配音，“阶段过程产物”按六个阶段展示所有已持久化中间结果。单阶段失败会自动重试一次，第二次仍失败则如实标记为 `partial`，并保留此前成功产物。Cosmos 失败时可以生成明确标记的降级视频，但不会冒充真实模型结果。

### 技术方案

后端使用 FastAPI、Pydantic、SQLite 和本地文件系统；前端使用 Vite、TypeScript 和 SSE。Qwen3.6、Step1X、Cosmos、Magpie 和 Nemotron 通过显式 adapter 接口接入，`ModelManager` 使用单一异步锁串行推理调用。

默认 safe-warm 策略如下：

- Nemotron ASR 与 Magpie TTS 常驻。
- vLLM 在 Campaign 间隔预热，进入 Step1X/Cosmos 视觉阶段前释放。
- Step1X 仅在实测统一内存余量足够时才可选常驻。
- Cosmos 始终按需启动。
- 非常驻命令 adapter 运行在独立进程组中，超时或取消会终止完整进程组，避免残留 CUDA context。

上传不仅检查 MIME，还检查图片和音频容器签名。导出前会解析真实路径并拒绝符号链接越界，防止恶意 adapter 把 Campaign 目录外的文件打进 ZIP。

### NVIDIA 与 StepFun 技术栈

主模型为 NVIDIA 优化的 `nvidia/Qwen3.6-35B-A3B-NVFP4`，固定 revision 后由 native vLLM `0.25.1` 在 `127.0.0.1:8011` 提供 OpenAI-compatible 接口。运行时启用 FP8 KV cache、FlashInfer attention、Marlin MoE、chunked prefill、prefix caching 和 MTP speculative decoding。

视觉编辑使用 StepFun `Step1X-Edit-v1p2` FP8 权重；图生视频使用 NVIDIA Cosmos3-Edge 与 Cosmos Framework；语音识别使用 NVIDIA Nemotron 3.5 ASR Streaming 0.6B；语音合成使用 NVIDIA NeMo MagpieTTS Multilingual 357M 和 Nano Codec。所有 CUDA 重任务都在 DGX Spark 本地执行，ffmpeg 只负责字幕、音频和 MP4 封装。

### 实机结果与优化过程

native vLLM Run9 六阶段全部一次成功，端到端用时 `580.147s`。部署 safe-warm 版本后，UQ-14 真实 Campaign 用时 `451.296s`，六阶段同样全部一次成功；中、英、日 TTS 回听相似度分别为 `0.8333`、`1.0`、`0.88`，完整 ZIP 与三个单语言 ZIP 均通过完整性和语言隔离检查。

UQ-15 从音视频阶段重跑并在真实 TTS 请求中取消：旧 TTS PID 被终止，新进程自动恢复，启动计数从 `1` 增至 `2`，ASR 进程保持不变，服务未出现 OOM 或 CUDA 错误。优化过程包括把 Step1X 演示默认值从 8 步调整到经独立基准验证的 6 步、将 FlashInfer 首次 JIT 编译并行度限制为 1 以避免统一内存 OOM、让中文和日文视频脚本避免不可直接发音的拉丁缩写，以及在视觉阶段前卸载 vLLM。完整本地回归由 `./overseaark test` 统一执行后端、前端、生命周期、HTTP Mock E2E 和安全用例；具体用例数以当次测试输出为准。

### 团队分工与贡献

- 队长陈荣杰负责项目和技术的实施。
- 队员陈郑超负责产品与设计。
- 队员黄冬梅负责全流程质量把控。

### 未来展望

下一步首先补齐同一当前构建下的三轮连续 native vLLM 十分钟内实测，满足 PRD 的严格验收；同时持续验证 ASR/TTS 常驻进程在连续 Campaign 中的内存稳定性，并只在 119 GiB 统一内存余量充分时评估 Step1X 常驻。产品层面会加入可编辑品牌模板、人工审核节点、Campaign 对比和离线素材版本管理；工程层面会继续压缩冷启动、增加模型缓存可视化和内核级离线网络审计。所有扩展仍坚持 localhost、显式模型版本、失败不伪装和用户数据可完全删除。

## 配置

只有在需要修改默认值时才复制 `.env.example`：

```bash
cp .env.example .env
```

重要默认值：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `OVERSEAARK_HOST` | `127.0.0.1` | 只绑定 localhost。 |
| `OVERSEAARK_BACKEND_PORT` | `8000` | FastAPI API 和前端页面。 |
| `OVERSEAARK_MODELS_DIR` | `/home/Developer/overseaark-models` | 仓库外模型缓存。 |
| `OVERSEAARK_DATA_DIR` | `/home/Developer/overseaark-data` | SQLite、上传文件、产物和日志。 |
| `OVERSEAARK_ADAPTER_MODE` | `command` | DGX 上的真实本地 adapter。 |
| `OVERSEAARK_AUTO_BOOTSTRAP` | `1` | `start` 时自动修复缺失依赖。 |
| `OVERSEAARK_AUTO_DOWNLOAD_MODELS` | `1` | `start` 时自动修复缺失或损坏的锁定模型文件。 |
| `OVERSEAARK_RESIDENT_ADAPTERS` | `asr,tts` | 常驻 worker 列表；只有确认内存余量后才考虑追加 `image`。 |
| `OVERSEAARK_KEEP_VLLM_RESIDENT` | `0` | safe profile 下保持关闭；vLLM 在 Campaign 间隔预热，并在视觉阶段前释放。 |
| `OVERSEAARK_STEP1X_STEPS` | `6` | DGX 实测演示默认值；正式精修图片可调高。 |
| `OVERSEAARK_COSMOS_STEPS` | `28` | Cosmos3-Edge 默认推理步数。 |
| `OVERSEAARK_VLLM_ENV_DIR` | `.venv-vllm` | 隔离 native vLLM 环境。 |
| `OVERSEAARK_VLLM_PORT` | `8011` | 本地 OpenAI-compatible Qwen endpoint。 |
| `OVERSEAARK_VLLM_GPU_MEMORY_UTILIZATION` | `0.4` | DGX Spark vLLM 显存预算。 |
| `OVERSEAARK_VLLM_MAX_MODEL_LEN` | `262144` | DGX Spark 上的 Qwen3.6 上下文长度。 |

中国大陆网络默认使用 TUNA 和镜像，同时仍以锁定哈希为准：

```bash
MODELSCOPE_ENDPOINT=https://modelscope.cn
HF_ENDPOINT=https://hf-mirror.com
OVERSEAARK_PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
OVERSEAARK_PYPI_FILE_PREFIX=https://pypi.tuna.tsinghua.edu.cn/packages/
OVERSEAARK_PYTORCH_INDEX=https://mirrors.aliyun.com/pytorch-wheels/cu130
OVERSEAARK_GITHUB_GIT_PREFIX=https://gh-proxy.com/https://github.com/
OVERSEAARK_GITHUB_ASSET_PREFIX=https://ghfast.top/
```

把镜像前缀设为空字符串即可直接使用上游 URL。

## 模型栈

`model-manifest.lock.json` 是模型来源和文件校验的事实源。必需锁定文件总量为 81,211,096,221 字节（约 75.6 GiB）。如果同步可选 Cosmos-Predict2，清单总量为 85,535,325,812 字节。主 Qwen NVFP4 模型文件约 23.45 GB。

不要把 DGX Spark 显示的 119 GiB 统一内存理解为可以同时常驻所有模型。必需原始模型文件本身约 75.6 GiB，还未计算 vLLM KV cache、CUDA context、解码权重、Step1X/Cosmos activation、视频缓冲、操作系统和文件系统缓存。默认支持策略是 **safe-warm**：ASR/TTS 常驻，Step1X 经测量后可选常驻，vLLM 在 Campaign 间隔预热但在视觉阶段前释放，Cosmos 按需加载。

| 角色 | Manifest id | 来源 | Revision | 本地目录 | 必需 | License |
| --- | --- | --- | --- | --- | --- | --- |
| LLM/VLM | `qwen3.6-35b-a3b-nvfp4` | Hugging Face mirror 上的 `nvidia/Qwen3.6-35B-A3B-NVFP4` | `491c2f1ea524c639598bf8fa787a93fed5a6fbce` | `nvidia/qwen3.6-35b-a3b-nvfp4` | yes | Apache-2.0 |
| Image | `step1x-edit-v1p2` | Hugging Face mirror 上的 `stepfun-ai/Step1X-Edit-v1p2` | `ca85b97fd19f2235dc0d6fd3633d1319f169e149` | `stepfun/step1x-edit-v1p2` | yes | Apache-2.0 |
| Optional T2I | `cosmos-predict2-0.6b-text2image` | `nv-community/Cosmos-Predict2-0.6B-Text2Image`，NVIDIA upstream 的 ModelScope mirror | `master`，upstream `dd55b6858b22ad569976bff207880b8fea839da7` | `nvidia/cosmos-predict2-0.6b-text2image` | no | NVIDIA Open Model License |
| Video | `cosmos3-edge` | `nv-community/Cosmos3-Edge`，NVIDIA upstream 的 ModelScope mirror | `master`，upstream `6f58f6b4c91288838e60b6bcb2cc45d997e961de` | `nvidia/cosmos3-edge` | yes | NVIDIA Open Model Development Weight License 1.1 |
| Video VAE | `wan2.2-vae-cosmos3` | ModelScope 上的 `Wan-AI/Wan2.2-TI2V-5B` | `master`，upstream `921dbaf3f1674a56f47e83fb80a34bac8a8f203e` | `wan/wan2.2-vae` | yes | Apache-2.0 |
| ASR | `nemotron-asr-streaming-0.6b` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | `f3d333391852ba876df169dcc9ba902d25b6ab0b` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | yes | NVIDIA Open Model Development Weight License 1.1 |
| TTS codec | `nemo-nano-codec-22khz-1.89kbps-21.5fps` | `nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps` | `3c482a402a3c4cf33690a2c0f0a7d41afea6bd6a` | `nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps` | yes | NVIDIA Open Model License |
| TTS | `magpie-tts-multilingual-357m` | `nvidia/magpie_tts_multilingual_357m` | `34d7e40da85cabc97f92198889b65cea27bc7fd1` | `nvidia/magpie_tts_multilingual_357m` | yes | NVIDIA Open Model License |
| TTS tokenizer | `byt5-small-tokenizer` | `google/byt5-small` | `68377bdc18a2ffec8a0533fef03b1c513a4dd49d` | `google/byt5-small` | yes | Apache-2.0 |

固定框架版本：

| 组件 | 固定版本/Commit |
| --- | --- |
| native vLLM ARM64 CUDA wheel | `vLLM 0.25.1`，wheel SHA-256 `bdffbe35b2c1ab8f2a9dcc337b657261d9b192c92c217e5a2f98a8835fe78daa` |
| Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| NVIDIA-NeMo/NeMo for ASR | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |
| NeMo TTS environment | `nemo_toolkit[tts]==2.7.3` |

## 导出格式

完整导出按语言目录和共享目录组织，并保留兼容旧版的顶层条目：

```text
manifest.json
qc_report.json
shared/
  source_image.*
  poster.png
  video.mp4              # 有有效合成视频时存在
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

只有当前 Campaign 请求过的语言目录会出现。单语言导出只包含该语言的文案、音频和语言安全元数据；只有当视频配音语言与请求导出语言一致时才包含视频。

导出 manifest 记录模型 ID、revision、本地目录、license、阶段尝试次数和模型调用记录。

## API 示例

健康检查：

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

模型状态：

```bash
curl -sS http://127.0.0.1:8000/api/v1/models
```

转写音频：

```bash
curl -sS http://127.0.0.1:8000/api/v1/transcriptions \
  -F 'audio=@demo.wav;type=audio/wav' \
  -F 'language=auto'
```

创建 Campaign：

```bash
curl -sS http://127.0.0.1:8000/api/v1/campaigns \
  -F 'product_image=@product.png;type=image/png' \
  -F 'name=Travel charger launch' \
  -F 'description=A compact smart travel charger for global shoppers.' \
  -F 'source_market=CN' \
  -F 'target_markets=US,JP' \
  -F 'languages=zh,en,ja'
```

流式查看进度：

```bash
curl -N http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/events
```

从指定阶段重跑：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/rerun/media_production
```

预览已持久化媒体和质检产物：

```bash
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/poster
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/audio-en
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/video
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/assets/qc
```

有效 asset key 为 `source`、`poster`、`video`、`qc`、`audio-zh`、`audio-en` 和 `audio-ja`。产物只有在对应阶段成功后才可用。

取消和导出：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/cancel
curl -OJ http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export
curl -OJ 'http://127.0.0.1:8000/api/v1/campaigns/<campaign_id>/export?language=en'
```

## GPU 使用查看

Campaign 运行时，在 DGX Spark SSH 终端执行：

```bash
# 单次快照
nvidia-smi

# 实时查看利用率、功耗、频率、温度和 PCIe 活动
nvidia-smi dmon -s pucvmet
```

网页中也有可展开的 **在哪里查看 GPU 使用情况？ / Where can I view GPU usage?** 指引。它是操作提示，不是内嵌指标面板；实时数值仍在 SSH 终端中查看。

如果演示用后台监控正在运行，输出位于：

```bash
tail -f /home/Developer/overseaark-data/logs/gpu-dmon.log
```

DGX Spark 使用 CPU/GPU 统一内存，因此 `nvidia-smi` 的部分进程内存列可能显示 `N/A` 或 `Not Supported`。配合下面命令查看总体统一内存压力：

```bash
free -h
```

## 离线与安全边界

- 运行时服务绑定到 `127.0.0.1`。
- 生产前端资源由 FastAPI 在 `8000` 端口提供，不需要 `5173` tunnel。
- `validate_offline_runtime` 拒绝非本地 LLM base URL 和包含远程 URL 的 adapter 命令。
- 推理运行时设置 `TRANSFORMERS_OFFLINE=1`、`HF_HUB_OFFLINE=1` 和 `HF_DATASETS_OFFLINE=1`。
- 只有模型获取生命周期步骤会临时关闭 Hugging Face 离线标志。
- 模型文件校验会拒绝不安全路径、大小不匹配、SHA-256 不匹配，以及锁定模型根目录外的清理操作。
- 模型权重不提交到仓库。

本地机器 SSH tunnel 示例：

```bash
ssh -p 6105 \
  -L 8000:127.0.0.1:8000 \
  root@106.13.186.155
```

## 验证

本地安全验证：

```bash
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark doctor
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark models verify
OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark test
```

`./overseaark test` 会运行后端套件、前端类型/构建检查、生命周期对抗检查、后端 smoke test 和 Mock HTTP E2E。测试数量会随覆盖率变化，应以当前命令输出为准，不要引用文档中的固定数字。

启动后的手动浏览器 smoke test：

1. 打开 `http://127.0.0.1:8000`；确认默认语言为简体中文，切换到 **English**，刷新后确认语言选择保持。
2. 点击 **一键填入示例 / Fill demo**；确认图片和完整表单已填入，然后创建 Campaign。
3. 运行期间确认 SSE 进度递增，并且已完成阶段的结果会在整个 Campaign 结束前出现在 **阶段过程产物 / Stage artifacts**。
4. 在中文、English、Japanese 输出 tab 之间切换；确认本地化文案和音频跟随当前语言。
5. Campaign 进入 `completed` 或 `partial` 后，下载 **all languages** 和当前语言 ZIP，并检查语言目录边界。
6. 重任务阶段在 SSH 终端运行 `nvidia-smi dmon -s pucvmet`，阶段切换间隙运行 `free -h`。

真实模型校验：

```bash
./overseaark models verify
```

使用已校验模型做直接 adapter benchmark：

```bash
./overseaark benchmark llm
./overseaark benchmark image
./overseaark benchmark audio
./overseaark benchmark video
```

`benchmark audio` 会对 `zh`、`en`、`ja` 各运行三轮，使用每种语言两个 Magpie voice，检查指定语言和自动 Nemotron ASR，低于 `0.75` 相似度则失败。

## 赛事亮点

- 单仓库提供可复现本地运维路径。
- 无 Docker；目标路径是 DGX Spark 上的 native aarch64 Ubuntu 24.04。
- 固定 `nvidia/Qwen3.6-35B-A3B-NVFP4`，由隔离 `.venv-vllm` 中的 native vLLM `0.25.1` 提供服务，无 Docker runtime。
- vLLM 只监听 localhost `127.0.0.1:8011`，使用生命周期脚本中的 DGX Spark 参数：`--tensor-parallel-size 1`、`--kv-cache-dtype fp8`、`--attention-backend flashinfer`、`--moe-backend marlin`、`--max-model-len 262144`、`--max-num-seqs 4`、`--max-num-batched-tokens 8192`、chunked prefill、prefix caching 和 MTP speculative decoding。
- Step1X 默认 6 步；DGX image benchmark 为 `176.3s`，相较 run 3 节省约 45 秒，并保留可用商品海报。
- Cosmos3-Edge 默认 28 步，并使用固定 Wan2.2 VAE 依赖。
- Nemotron ASR 和 Magpie TTS 形成可度量的音频回听质检闭环。
- 推理调用串行化；ASR/TTS worker 保持就绪，vLLM 在 Campaign 间隔预热并在视觉阶段前释放，Step1X 常驻为 opt-in，Cosmos 按需启动。
- 六阶段过程产物在执行中可见，本地化视图和单语言导出保持 `zh`、`en`、`ja` 内容隔离。
- 缺失模型和损坏但同大小的锁定文件可通过重新运行 `./overseaark start` 自动修复。
- 导出 manifest 记录模型 ID、revision、license、阶段尝试次数和模型调用。

## 故障排查

| 现象 | 可能原因 | 处理方式 |
| --- | --- | --- |
| `runtime dependencies are incomplete` | Bootstrap 未完成或固定 venv 缺少 import。 | 重新运行 `./overseaark start`；缓存会复用。如果重复出现，查看 `./overseaark logs all`。 |
| `Qwen3.6 NVFP4 is missing` | `OVERSEAARK_MODELS_DIR` 中缺少必需模型文件。 | 运行 `./overseaark start` 或 `./overseaark models sync`。 |
| `model manifest verification` 失败 | 锁定文件缺失、截断或 SHA 不匹配。 | 重新运行 `./overseaark start`；无效锁定文件会被删除并重新获取。 |
| `pinned native vLLM is missing` | `.venv-vllm` 不存在，或未安装固定 CUDA ARM64 wheel。 | 重新运行 `./overseaark bootstrap`；只有强制干净重装时才先删除 `.venv-vllm`。 |
| 第一次 vLLM 启动很慢 | FlashInfer 正在编译并缓存 GB10/SM121 kernel。 | 保持首次启动继续运行。JIT 已用 `MAX_JOBS=1` 串行化以避免统一内存 OOM；已验证冷缓存启动用时 526 秒，后续完整重启用时 166 秒。查看 `./overseaark logs llm`。 |
| Adapter timeout | 重模型超过 `OVERSEAARK_ADAPTER_TIMEOUT`。 | 检查 `OVERSEAARK_ADAPTER_TIMEOUT`、模型日志和 GPU 内存压力；超时时进程组会被终止。 |
| 常驻启动失败或内存压力增长 | 当前 warm profile 对统一内存余量过于激进。 | 恢复 `OVERSEAARK_RESIDENT_ADAPTERS=asr,tts` 和 `OVERSEAARK_KEEP_VLLM_RESIDENT=0`，重启后查看 `free -h` 和 `/api/v1/models`。 |
| `export?language=...` 返回 422 | 语言代码不受支持，或该 Campaign 未请求该语言。 | 使用 `zh`、`en` 或 `ja`，并且必须是创建 Campaign 时包含的语言。 |
| 前端显示 degraded local preview | 浏览器无法访问后端。 | 检查 `./overseaark status` 和 `http://127.0.0.1:8000/api/v1/health`。 |
| 上传返回 415 | content type 不受支持，或文件字节与声明类型不匹配。 | 商品图使用真实 PNG/JPEG/WebP，音频使用 WAV/MP3/M4A/WebM。 |
| 导出返回 409 | Campaign 尚未到达 packaging，且没有可用 partial export。 | 等待 Campaign 进入终态，或检查阶段错误。 |

## 更多文档

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Competition Notes](docs/COMPETITION.md)
- [Model Licenses](docs/MODEL_LICENSES.md)
- [PRD v2.0（Markdown）](docs/PRD-v2.0.md)
- [PRD v2.0（Word）](docs/出海方舟OverseaArk-PRD-v2.0.docx)
