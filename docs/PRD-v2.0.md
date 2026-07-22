# 出海方舟 OverseaArk 产品需求文档 v2.0

产品展示名：DGX Spark一支不下班的本地多模态外贸营销团队
项目代号：出海方舟 OverseaArk
产品定义：一台 NVIDIA DGX Spark 上本地运行、可观测、可恢复、可导出的多模态外贸营销工作台。

| 字段 | 内容 |
| --- | --- |
| 文档版本 | v2.0 |
| 文档状态 | 当前实施与赛事交付基线 |
| 更新日期 | 2026-07-22 |
| 代码形态 | 单仓 Monorepo |
| 目标平台 | NVIDIA DGX Spark，Ubuntu 24.04，aarch64，CUDA 13 |
| 服务形态 | FastAPI 单端口托管 API 与 Vite 构建产物 |
| 首发语言 | 中文 zh、英文 en、日文 ja |
| 核心推理 | 全部在 DGX Spark 本地完成，不使用云端生成 API |

## 1. 执行摘要

OverseaArk 面向中小外贸企业、跨境卖家和代运营团队，把市场定位、买家画像、多语文案、产品视觉、配音视频和质量打包收敛为一条六阶段流水线。用户只需提供产品图和产品描述，即可获得中英日文案、产品海报、三语配音、480p 短视频、质量报告和可按语言拆分的 ZIP 交付包。

v2.0 不是概念稿，而是对当前可运行系统的产品合同。它以 native vLLM、Step1X、Cosmos3-Edge、Nemotron ASR、Magpie TTS 和 ffmpeg 为固定技术栈，以 safe-warm 模型策略适配 DGX Spark 的 119 GiB 统一内存，并通过 SSE、SQLite、阶段产物预览、重跑、取消和导出形成可演示、可恢复、可审计的闭环。

## 2. 背景与问题

外贸营销素材生产通常分散在多个云端工具和人工环节中，存在以下问题：

- 产品图、工艺、报价和未发布卖点需要在不同服务之间流转，数据边界不清晰。
- 市场定位、翻译、海报、配音、视频和质检由不同工具完成，交付格式不一致。
- 生成过程不可观测，失败后经常需要从头开始，已有成果难以保留。
- 现场演示需要频繁加载模型，若缺少统一内存调度，容易出现 OOM、残留 CUDA 进程和长时间等待。
- 完整多语包和单语言交付包没有清晰边界，容易泄露不应出现的其他语言内容。

OverseaArk 的解法是在本地设备上建立一个明确状态机、固定模型清单和可验证导出合同，而不是继续拼接更多云端工具。

## 3. 产品目标与非目标

### 3.1 产品目标

1. 一次输入生成完整的中英日外贸营销物料包。
2. 所有主生成模型在 DGX Spark 本地运行，产品资料不发送到云端推理服务。
3. 六阶段执行过程实时可见，刷新页面后可以恢复进度和历史事件。
4. 每个已完成阶段的中间产物立即可预览，不必等待整个 Campaign 结束。
5. 完整导出按语言目录组织，同时支持只导出当前语言且不夹带其他语言元数据。
6. 缺少或损坏的依赖、模型文件可由根目录脚本自动校验和修复。
7. 在不牺牲稳定性的前提下降低重复模型加载时间，并对 OOM 风险保持真实边界。

### 3.2 非目标

- 不提供 Docker 部署路径。
- 不使用 ComfyUI、OpenClaw、Ollama、NIM 云 API、StepFun 云 API 或 NVIDIA 托管推理 API。
- 不开放公网监听，不提供多租户 SaaS、账号计费或公网鉴权系统。
- 不开放用户声音克隆。
- 不把 Cosmos 失败后的 ffmpeg 静态视频冒充为模型视频。
- v2.0 不承诺中文、英文、日文之外的完整语音闭环。

## 4. 目标用户与核心价值

| 用户 | 核心场景 | 主要痛点 | 产品价值 |
| --- | --- | --- | --- |
| 中小外贸卖家 | 新品上架、社媒投放、开发信 | 外包周期长，工具成本高 | 一次输入生成完整 Campaign 包 |
| 外贸工厂 | 向海外采购商展示产品 | 工艺和产品资料敏感 | 本地推理，数据留在设备内 |
| 跨境运营 | 中英日内容复用 | 文案、图片、视频和语音割裂 | 六阶段统一状态与导出合同 |
| 演示与评审人员 | 现场观察 DGX Spark 价值 | 需要快速、直观、可复现 | 一键示例、实时产物、GPU 监控指引 |

## 5. 核心用户旅程

1. 用户通过 SSH 隧道打开 `http://127.0.0.1:8000`。
2. 工作台默认显示中文，用户可切换为英文，选择会保存在浏览器中。
3. 用户上传 PNG、JPEG 或 WebP 产品图，填写产品描述、来源市场、目标市场和输出语言。
4. 演示场景可点击“一键填入示例”，自动填入示例图片、完整产品说明、市场和中英日选项。
5. 用户创建 Campaign，页面通过 SSE 展示六阶段状态和递增事件序号。
6. 阶段完成后，结构化文本、海报、音频、视频和质检结果立即出现在“阶段过程产物”。
7. 用户可在“本地化输出”中切换 zh、en、ja，只查看当前语言的文案与音频。
8. 用户可以取消执行，或从指定阶段重跑并保留此前成功成果。
9. 完成或部分完成后，用户下载完整多语 ZIP 或当前语言 ZIP。

## 6. 功能范围与优先级

| 优先级 | 功能 | v2.0 状态 |
| --- | --- | --- |
| P0 | 一键启动、依赖安装、模型自动校验与下载 | 已实现 |
| P0 | 六阶段串行 Campaign 流水线 | 已实现 |
| P0 | 中英日文案、配音、回听质检 | 已实现 |
| P0 | Step1X 产品视觉和 Cosmos3-Edge 视频 | 已实现 |
| P0 | SSE 进度、刷新恢复、阶段产物预览 | 已实现 |
| P0 | 完整导出与单语言隔离导出 | 已实现 |
| P0 | 阶段重试、partial、取消和进程清理 | 已实现 |
| P0 | 中文默认界面与英文界面切换 | 已实现 |
| P1 | 可选 Cosmos-Predict2 纯文生图灵感能力 | 模型清单可选，未进入主流程 |
| P1 | 可编辑品牌模板和人工审核节点 | 后续版本 |
| P2 | 多 Campaign 对比和离线素材版本管理 | 后续版本 |

## 7. 六阶段 Pipeline 合同

阶段顺序和枚举必须与后端 `StageName` 保持一致。

| 顺序 | 阶段枚举 | 主要模型或工具 | 主要输出 |
| --- | --- | --- | --- |
| 1 | `market_positioning` | Qwen3.6 NVFP4 via native vLLM | 定位、差异化、市场假设 |
| 2 | `buyer_persona` | Qwen3.6 NVFP4 via native vLLM | 买家画像、痛点、购买动机、渠道建议 |
| 3 | `multilingual_copy` | Qwen3.6 NVFP4 via native vLLM | zh/en/ja 标题、卖点、详情、开发信、视频脚本 |
| 4 | `visual_design` | Step1X-Edit-v1p2 FP8 + Pillow | `visual_design.png` 产品海报 |
| 5 | `media_production` | Magpie TTS、Cosmos3-Edge、ffmpeg | 三语 WAV、模型视频、字幕、`campaign_video.mp4` |
| 6 | `quality_packaging` | Nemotron ASR、文件检查、ZIP | `qc_report.json`、`manifest.json`、导出包 |

### 7.1 阶段执行规则

- 所有 GPU 重任务由同一个 `ModelManager` 锁串行调度。
- 每个阶段首次失败后自动重试一次。
- 第二次仍失败时，当前阶段为 `failed`，后续阶段为 `skipped`。
- 已存在有效产物时 Campaign 进入 `partial`；没有可用成果时进入 `failed`。
- 取消后 Campaign 为 `cancelled`，成功的早期阶段及其产物保留。
- Cosmos 失败时允许生成明确标记为 `degraded` 的 ffmpeg 兜底产物，但 Campaign 不得因此标记为 `completed`。

### 7.2 状态枚举

| 类型 | 允许值 |
| --- | --- |
| CampaignStatus | `queued`、`running`、`completed`、`partial`、`failed`、`cancelled` |
| StageStatus | `pending`、`running`、`succeeded`、`failed`、`skipped` |

模型加载、保存、降级和进度百分比属于事件或消息字段，不新增状态枚举。

## 8. 多语言、语音与质量闭环

### 8.1 语言合同

- 工作台界面默认简体中文，可切换为 English。
- 内容输出固定支持 `zh`、`en`、`ja`，可选择一种或多种语言。
- 本地化输出区域只能展示当前所选语言的文案与配音。
- 海报、视频和 QC 等共享产物不得被错误归类为英文产物。

### 8.2 TTS 合同

| 语言 | 默认音色 |
| --- | --- |
| 中文 | Sofia |
| 英语 | Jason |
| 日语 | Aria |

- TTS 长文本按标点切分，单段目标不超过 20 秒，最终合并为 WAV。
- 不开放用户声音克隆。
- TTS 失败不静默切换到其他模型。

### 8.3 ASR 回听质检

Magpie 生成每种语言的音频后，由 Nemotron 重新转写，并计算规范化文本相似度。低于 `0.75` 时只重做失败语言一次；第二次仍不达标则如实保留证据并使 Campaign 进入 `partial`。

## 9. 前端体验与可观测性

### 9.1 工作台要求

- 产品展示名固定为“DGX Spark一支不下班的本地多模态外贸营销团队”。
- 第一屏包含创建表单、一键填入示例、API 与模型健康状态。
- 六阶段列表显示当前状态、尝试次数和错误信息。
- 已持久化的阶段输出直接出现在“阶段过程产物”。
- 海报、音频、视频和 QC 文件提供内嵌预览或下载入口。
- 页面刷新后通过 Campaign ID 恢复详情，SSE 从最后序号继续。

### 9.2 SSE 合同

事件带严格递增 `sequence`，支持查询参数或 `Last-Event-ID` 恢复；客户端忽略重复或乱序事件。`stage.succeeded` 事件携带的输出可立即合并到前端，不等待下一次轮询；较旧的轮询响应不得覆盖较新的 SSE 状态。

## 10. 产物与导出合同

### 10.1 产物目录

所有 Campaign 产物位于：

```text
/home/Developer/overseaark-data/artifacts/{campaign_id}/
```

典型文件包括：

```text
visual_design.png
voice_zh.wav
voice_en.wav
voice_ja.wav
cosmos_video.mp4
campaign_video.mp4
subtitles_en.srt
qc_report.json
manifest.json
export.zip
```

### 10.2 完整导出

完整 ZIP 必须包含 `shared/` 和该 Campaign 实际请求的语言目录：

```text
shared/
zh/
en/
ja/
manifest.json
qc_report.json
```

共享目录存放产品源图、海报、视频和通用报告；语言目录存放对应文案和音频。

### 10.3 单语言导出

`GET /api/v1/campaigns/{id}/export?language=zh|en|ja` 只导出当前语言及合法共享产物，并递归过滤：

- 其他语言的文案和音频。
- `manifest.languages` 中的其他语言。
- QC 中其他语言的音频记录。
- `model_calls` 中其他语言调用信息。
- 配音语言不匹配的视频。

导出器只允许读取 uploads 与当前 Campaign artifacts 根目录内的文件，拒绝绝对路径、`..` 和符号链接越界。

## 11. 当前模型与框架基线

`model-manifest.lock.json` 是模型文件、大小、SHA256、来源、许可证和 revision 的唯一事实来源。

| 能力 | 模型与来源 | 固定修订 | 必需性 |
| --- | --- | --- | --- |
| LLM/VLM | `nvidia/Qwen3.6-35B-A3B-NVFP4` | `491c2f1ea524c639598bf8fa787a93fed5a6fbce` | 必需 |
| 图片编辑 | `stepfun-ai/Step1X-Edit-v1p2` | `ca85b97fd19f2235dc0d6fd3633d1319f169e149` | 必需 |
| 纯文生图 | `nvidia/Cosmos-Predict2-0.6B-Text2Image` 的 ModelScope 镜像 | upstream `dd55b6858b22ad569976bff207880b8fea839da7` | 可选 |
| 图生视频 | `nvidia/Cosmos3-Edge` 的 ModelScope 镜像 | upstream `6f58f6b4c91288838e60b6bcb2cc45d997e961de` | 必需 |
| 视频 VAE | `Wan-AI/Wan2.2-TI2V-5B` 中固定 VAE | upstream `921dbaf3f1674a56f47e83fb80a34bac8a8f203e` | 必需 |
| ASR | `nvidia/nemotron-3.5-asr-streaming-0.6b` | `f3d333391852ba876df169dcc9ba902d25b6ab0b` | 必需 |
| TTS | `nvidia/magpie_tts_multilingual_357m` | `34d7e40da85cabc97f92198889b65cea27bc7fd1` | 必需 |
| TTS Codec | `nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps` | `3c482a402a3c4cf33690a2c0f0a7d41afea6bd6a` | 必需 |
| TTS Tokenizer | `google/byt5-small` tokenizer | `68377bdc18a2ffec8a0533fef03b1c513a4dd49d` | 必需 |

固定框架版本：

| 组件 | 版本或 Commit |
| --- | --- |
| native vLLM ARM64 CUDA | vLLM `0.25.1`，wheel SHA256 `bdffbe35b2c1ab8f2a9dcc337b657261d9b192c92c217e5a2f98a8835fe78daa` |
| Step1X diffusers 分支 | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| NVIDIA Cosmos Framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| NVIDIA NeMo ASR | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |
| NeMo TTS 环境 | `nemo_toolkit[tts]==2.7.3` |

## 12. Safe-warm 统一内存策略

DGX Spark 提供约 119 GiB 统一内存，但必需模型原始文件约 75.6 GiB；运行时还需要解码权重、KV cache、CUDA context、Step1X/Cosmos 激活、视频缓冲、操作系统和文件缓存。所有模型同时常驻缺少可靠 OOM 余量，因此 v2.0 明确采用 safe-warm，而不是声称全模型常驻。

| 组件 | 默认策略 |
| --- | --- |
| Nemotron ASR | 常驻 JSONL 工作进程 |
| Magpie TTS | 常驻 JSONL 工作进程 |
| Qwen vLLM | Campaign 间预热；进入视觉阶段前释放 |
| Step1X | 默认按需；仅在实测余量充足时允许可选常驻 |
| Cosmos3-Edge | 始终按需启动 |

默认配置为：

```text
OVERSEAARK_RESIDENT_ADAPTERS=asr,tts
OVERSEAARK_KEEP_VLLM_RESIDENT=0
```

`GET /api/v1/models` 必须报告 `all_models_resident=false`、safe-warm 策略、预热状态、常驻 worker PID、ready 状态和启动次数。

取消、超时或致命 CUDA 错误时，系统终止相关工作进程组；Campaign 结束或取消后重新准备空闲模型组合。

## 13. 系统架构与仓库边界

```text
overseaark/
  frontend/                 # Vite + TypeScript + CSS
  backend/                  # FastAPI、SQLite、Pipeline、ModelManager
  scripts/                  # 安装、模型、生命周期、adapter、benchmark
  docs/                     # PRD、架构、部署、赛事和测试材料
  tests/e2e/                # Mock 与生命周期端到端测试
  runtime/frontend-dist/    # 被忽略的前端构建产物
  model-manifest.lock.json  # 固定模型清单
  overseaark                # 根目录一键入口
```

| 类型 | 路径 |
| --- | --- |
| 代码 | `/home/Developer/overseaark` |
| 模型 | `/home/Developer/overseaark-models` |
| 用户数据 | `/home/Developer/overseaark-data` |
| FastAPI 与前端 | `127.0.0.1:8000` |
| native vLLM | `127.0.0.1:8011` |

模型、数据库、日志、上传、生成素材、凭据和前端构建产物均不得提交到 Git。

## 14. API v1 合同

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 服务与模型准备状态 |
| `GET` | `/health` | 兼容健康检查 |
| `GET` | `/api/v1/models` | 模型、离线、串行和 safe-warm 状态 |
| `POST` | `/api/v1/transcriptions` | 上传音频并执行本地 ASR |
| `POST` | `/api/v1/campaigns` | multipart 创建 Campaign |
| `GET` | `/api/v1/campaigns` | Campaign 列表 |
| `GET` | `/api/v1/campaigns/{id}` | Campaign、阶段和产物详情 |
| `GET` | `/api/v1/campaigns/{id}/events` | 可恢复 SSE 事件流 |
| `POST` | `/api/v1/campaigns/{id}/rerun` | 从第一阶段重跑 |
| `POST` | `/api/v1/campaigns/{id}/rerun/{stage}` | 从指定阶段重跑 |
| `POST` | `/api/v1/campaigns/{id}/cancel` | 取消 Campaign |
| `GET` | `/api/v1/campaigns/{id}/assets/{asset_key}` | 安全读取源图、海报、音频、视频或 QC |
| `GET` | `/api/v1/campaigns/{id}/export` | 完整导出，或通过 `language` 查询参数单语言导出 |

## 15. 一键启动与模型获取

### 15.1 根命令

```text
./overseaark bootstrap
./overseaark start
./overseaark stop
./overseaark restart
./overseaark status
./overseaark logs all
./overseaark doctor
./overseaark models verify
./overseaark models sync
./overseaark benchmark llm|image|audio|video
./overseaark test
```

`./overseaark start` 是主要入口，必须完成：

1. 检查并修复基础依赖。
2. 使用隔离环境安装 native vLLM、Step1X、Cosmos、NeMo ASR 和 NeMo TTS。
3. 根据 lock manifest 校验模型 revision、文件大小和 SHA256。
4. 删除损坏文件并断点下载缺失文件。
5. 构建前端并启动本地 vLLM 与 FastAPI。
6. 等待健康检查，同时在后台完成 ASR/TTS 常驻预热。

### 15.2 国内网络加速

| 用途 | 默认地址 |
| --- | --- |
| Python 包 | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| Hugging Face | `https://hf-mirror.com` |
| ModelScope | `https://modelscope.cn` |
| CUDA PyTorch wheel | `https://mirrors.aliyun.com/pytorch-wheels/cu130` |

模型镜像只改变传输来源，固定 revision、大小和 SHA256 仍是完整性依据。

### 15.3 远程访问

```bash
ssh -p 6105 -L 8000:127.0.0.1:8000 root@106.13.186.155
```

服务保持只监听 `127.0.0.1`，不开放 DGX 的公网端口。

## 16. 安全、隐私与离线边界

- Campaign 主生成阶段设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 和 `HF_DATASETS_OFFLINE=1`。
- LLM 地址必须解析为 localhost，拒绝远程 adapter URL。
- 上传同时校验 MIME、大小和真实文件签名。
- 产品图片最大 20 MiB，仅允许 PNG、JPEG、WebP。
- 音频只允许受支持的 WAV、MP3、M4A、WebM 容器签名。
- 导出文件真实路径必须位于允许的 uploads 或当前 Campaign artifacts 根目录。
- 日志不主动记录密钥；vLLM API key 存放在本地运行目录。
- 推理期间只允许 localhost、本地文件、SQLite、Unix 进程和 ffmpeg 通信。
- 本版本未完成内核级抓包审计，因此不得把环境变量隔离描述为防火墙级证明。

## 17. 非功能需求

| 类别 | 要求 |
| --- | --- |
| 性能 | 缓存就绪后的默认完整 Campaign 目标不超过 10 分钟 |
| 稳定性 | 不出现 OOM、CUDA context 污染或残留重型模型进程 |
| 可恢复性 | 后端重启后恢复 queued/running Campaign；SSE 可续传 |
| 可观测性 | 页面显示 API、模型准备状态、阶段、事件序号和产物 |
| 可维护性 | 单仓、单 README 主入口、单根命令、固定 lock manifest |
| 可测试性 | Mock 单元/E2E、生命周期对抗测试、DGX 真机 E2E |
| 可访问性 | PRD 使用真实标题层级；DOCX 表格标记标题行 |

## 18. 验收标准与当前证据

| 编号 | 验收项 | 标准 | 当前状态 |
| --- | --- | --- | --- |
| AT-001 | 连续三次完整运行 | 同一当前构建连续 3 个 Campaign `completed`，每次不超过 10 分钟 | 未完全满足 |
| AT-002 | 三语言输出 | zh/en/ja 文案与音频齐全 | 已满足 |
| AT-003 | ASR/TTS 闭环 | Magpie 生成，Nemotron 回听 | 已满足 |
| AT-004 | 回听相似度 | 每种语言不低于 `0.75` | 已满足单轮与回归测试 |
| AT-005 | 视频 | 至少 480p，ffprobe 可读 | 已满足 |
| AT-006 | 重试与 partial | 失败重试一次，仍失败时保留成果 | 已满足 |
| AT-007 | 降级语义 | ffmpeg 兜底明确 degraded，不冒充完成 | 已满足 |
| AT-008 | OOM 与残留 | 完整运行和取消后无 OOM、无孤儿进程 | 已满足当前实测 |
| AT-009 | 离线 | 主推理链路不访问公网 | 环境与地址边界已满足；内核抓包待补 |
| AT-010 | 导出隔离 | 完整包与单语言包完整、无跨语言泄露 | 已满足 |
| AT-011 | 国际化 | 默认中文，英文切换持久化 | 已满足 |
| AT-012 | 一键演示 | 一键示例可填入并创建完整 Campaign | 已满足 |

### 18.1 真机与对抗性证据

- Run8：真实模型均完成生成，但中文混合拉丁缩写导致回听低于阈值，Campaign 如实保持 `partial`，由此修复了口播生成规则。
- Run9：native vLLM 六阶段全部一次成功，用时 `580.147219s`；zh/en/ja 相似度为 `0.9375`、`1.0`、`0.9189`。
- UQ-14：当前 safe-warm 部署六阶段全部一次成功，用时 `451.296015s`；zh/en/ja 相似度为 `0.8333`、`1.0`、`0.88`；完整和三个单语言 ZIP 均通过完整性与语言隔离检查。
- UQ-15：只在真实 TTS 请求执行中取消；旧 TTS 进程被终止，新常驻进程自动恢复且启动计数增加，ASR 未被误杀，无 Step1X/Cosmos 孤儿进程。
- 本地完整门禁：后端 84 项、前端 25 项、HTTP E2E 14 项通过，另含类型检查、构建、生命周期和后端烟测。

Run9 和 UQ-14 是两次独立的十分钟内结果，但尚未形成同一当前构建连续三次达标的完整序列，因此不得宣称 AT-001 已完成。

## 19. 团队分工与贡献

| 成员 | 角色 | 分工与贡献 |
| --- | --- | --- |
| 陈荣杰 | 队长 | 负责项目和技术的实施 |
| 陈郑超 | 队员 | 负责产品与设计 |
| 黄冬梅 | 队员 | 负责全流程质量把控 |

团队协作以同一 PRD、同一代码仓库、同一验收标准和可复现证据为边界。技术实现、产品设计和质量把控分别有明确负责人，但最终交付以六阶段全链路是否真实可运行作为共同判断标准。

## 20. 风险与后续路线

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 统一内存峰值 | Step1X/Cosmos 转换时可能 OOM | 保持 safe-warm、串行锁和阶段前释放 vLLM |
| 国内网络不稳定 | 首次模型下载时间不可预测 | 固定镜像、断点续传、大小和 SHA256 校验 |
| ASR 对混合字符敏感 | TTS 回听可能低于阈值 | 生成本地可发音脚本，只重试失败语言 |
| 视频质量随样例变化 | 演示观感不稳定 | 固定默认样例和推理参数，保留真实质量标记 |
| 三轮严格证据未闭合 | 不能完全声明性能验收完成 | 在同一当前构建补跑连续三轮并保存 benchmark 证据 |
| 环境变量离线非内核隔离 | 无法证明网络层绝对零外连 | 后续增加受控抓包或网络命名空间审计 |

后续版本优先级：

1. 完成同一构建连续三轮十分钟内验收。
2. 增加品牌模板、人工审核节点和素材版本管理。
3. 增强模型缓存与统一内存可视化。
4. 增加 Campaign 对比、可编辑文案和批量导出。
5. 在不破坏 localhost 与离线边界的前提下扩展更多语言。

## 21. 发布定义

v2.0 可交付必须同时满足：

- 根命令可在无 Docker 的 DGX Spark 上启动系统并自动修复缺失模型。
- 中文默认界面、英文切换、一键示例和六阶段进度可用。
- 当前语言输出与阶段过程产物边界清晰。
- 完整导出和单语言导出通过完整性、安全与隔离测试。
- 所有失败、重试、取消、降级和质量结果如实记录。
- README、英文 README、PRD、架构、部署、模型清单和测试报告描述同一套技术事实。
- 不删除或覆盖用户未授权的项目外原始资料。

本 PRD v2.0 是 OverseaArk 当前唯一有效的产品需求基线。旧版 PRD 中出现的 Step-3.7、llama.cpp、ComfyUI、FLUX、Piper、StepAudio、云端推理或全模型常驻等描述均不再适用。
