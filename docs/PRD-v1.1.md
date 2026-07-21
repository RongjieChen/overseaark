# 出海方舟 OverseaArk 产品需求文档 v1.1

本地多模态外贸营销作战室。一台 NVIDIA DGX Spark = 一支本地运行的多模态外贸营销团队。

| 字段 | 内容 |
| --- | --- |
| 文档版本 | v1.1 |
| 文档状态 | 实施基线稿 |
| 日期 | 2026-07-22 |
| 代码形态 | OverseaArk monorepo |
| 目标平台 | NVIDIA DGX Spark, Ubuntu 24.04, aarch64, CUDA 13 |
| 运行时 | Python 3.12, FastAPI, Vite TypeScript, SQLite, ffmpeg |
| 语言范围 | 中文 zh、英文 en、日文 ja |
| 离线边界 | 主生成链路不调用 ComfyUI、OpenClaw、StepFun 云 API、NVIDIA 托管推理 API 或其他云端生成 API |

## 修订记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v1.0 | 2026-07-21 | 初版，定义外贸营销作战室方向 |
| v1.1 | 2026-07-22 | 对齐最终实机实现：Qwen3.6 GGUF、CUDA llama.cpp、Step1X、Cosmos3-Edge、NeMo 音频栈、按需模型卸载、自动下载与对抗性验收 |

## 1. 产品定位

出海方舟 OverseaArk 是部署在 DGX Spark 上的本地多模态外贸营销 campaign 工作台。用户上传产品图，填写产品描述、来源市场、目标市场和 zh/en/ja 语言配置，系统用六个固定阶段生成市场定位、买家画像、多语言文案、视觉图、视频/语音素材、质量报告和导出包。

v1.1 的重点不是扩展云端能力，而是证明一台本地 DGX Spark 能把敏感产品资料留在本机，同时完成可观测、可重跑、可导出的多模态 Agent 流水线。

## 2. 用户与目标

| 用户 | 场景 | 痛点 | v1.1 价值 |
| --- | --- | --- | --- |
| 中小外贸卖家 | 新品上架、社媒投放 | 外包慢，云端工具成本高 | 本地生成 campaign 物料包 |
| 外贸工厂 | 面向海外采购商展示产品 | 产品图、工艺、报价资料敏感 | 主链路离线，数据留在 `/home/Developer/overseaark-data` |
| 跨境运营 | zh/en/ja 内容复用 | 文案、图片、视频、配音割裂 | 六阶段统一编排和导出 |
| 演示评委 | 现场观察系统能力 | 需要看见 DGX Spark 价值 | 统一内存串行调度、SSE 进度和离线证据 |

### 2.1 成功指标

| 类别 | 指标 | 目标 |
| --- | --- | --- |
| 端到端 | 默认样例完整生成 | <= 10 分钟 |
| 语言 | 文案、TTS、ASR 校验覆盖 | zh/en/ja 三种 |
| 离线 | 主生成链路公网请求 | 0 |
| 稳定 | OOM、模型进程残留 | 0 |
| 视频 | 输出 campaign_video.mp4 | 至少 480p，可被 ffprobe 读取 |
| 质量 | ASR 回读与 TTS 输入相似度 | >= 0.75 |
| 重试 | 阶段失败后保留已有产物 | campaign 进入 `partial` |

## 3. Monorepo 范围

v1.1 的仓库结构固定如下，其他目录方案不属于本版本合同。

```text
overseaark/
  frontend/                 # Vite TypeScript 工作台源码
  backend/                  # FastAPI 服务、SQLite 存储、Pipeline、ModelManager
  scripts/                  # root lifecycle、model verify、adapter scripts
  docs/                     # PRD、架构、部署、竞赛和模型文档
  tests/e2e/                # 端到端契约测试和 mock server
  runtime/frontend-dist/    # 生产构建后的前端静态资源
  model-manifest.lock.json  # 固定模型清单和修订号
  overseaark                # root 命令入口
```

### 3.1 本地数据与模型路径

| 类型 | 固定路径 | 说明 |
| --- | --- | --- |
| 项目根目录 | `/home/Developer/overseaark` | DGX Spark 上的运行目录 |
| 数据目录 | `/home/Developer/overseaark-data` | SQLite、uploads、artifacts、logs、pid 文件 |
| 模型目录 | `/home/Developer/overseaark-models` | 本地模型权重，不提交到 Git |
| 前端构建目录 | `runtime/frontend-dist` | FastAPI 单端口静态服务输入 |

## 4. 六阶段 Pipeline

阶段名称、顺序和输出是产品合同，必须与后端 `StageName` 保持一致。

| 顺序 | 阶段枚举 | 模型/工具 | 主要输出 |
| --- | --- | --- | --- |
| 1 | `market_positioning` | Qwen3.6-35B-A3B Q4_K_M + BF16 mmproj | `positioning`、`differentiators`、目标市场上下文 |
| 2 | `buyer_persona` | Qwen3.6-35B-A3B | personas、采购动机、决策触发点 |
| 3 | `multilingual_copy` | Qwen3.6-35B-A3B | zh/en/ja 的标题、卖点、详情、开发信和短视频脚本 |
| 4 | `visual_design` | Step1X-Edit-v1p2 FP8 layerwise + Pillow | `visual_design.png`；生成背景与产品编辑后再由 Pillow 排字 |
| 5 | `media_production` | Cosmos3-Edge、Wan2.2 VAE、Magpie TTS、ffmpeg | `cosmos_video.mp4`、`campaign_video.mp4`、三语 WAV 和英文字幕 |
| 6 | `quality_packaging` | Nemotron ASR、确定性文件检查、zip | `manifest.json`、`qc_report.json`、`export.zip` |

### 4.1 Cosmos 约束

Cosmos3-Edge 是 required video model，通过固定版本 NVIDIA Cosmos Framework 直接推理，使用本地 Wan2.2 VAE 作为 vision tokenizer 依赖，输出 832×480、24 fps、121 帧的真实图生视频。Cosmos-Predict2 仅是 optional pure text-to-image 灵感图能力，不是阶段 5 的视频依赖。

默认推理预算为 Step1X 6 步、Cosmos3-Edge 28 步；这是 DGX Spark 演示模式的实测平衡点，Step1X 单项基准为 176.3 秒，并可通过环境变量提高质量预算。Cosmos 真模型失败时，只有显式允许才生成标记为 `degraded` 的 ffmpeg 兜底视频；该产物不能让阶段冒充成功。

### 4.2 阶段状态

Campaign 状态枚举仅为：

| 状态 | 含义 |
| --- | --- |
| `queued` | 已创建并等待执行 |
| `running` | pipeline 正在执行 |
| `completed` | 六阶段全部成功 |
| `partial` | 至少一个阶段最终失败，但已有有效产物被保留 |
| `failed` | 无可用产物或无法建立 campaign |
| `cancelled` | 用户取消 |

Stage 状态枚举仅为：

| 状态 | 含义 |
| --- | --- |
| `pending` | 阶段尚未开始 |
| `running` | 阶段执行中 |
| `succeeded` | 阶段成功并写入输出 |
| `failed` | 阶段两次尝试后仍失败 |
| `skipped` | 上游失败或取消后跳过 |

模型加载、保存中、降级说明、进度百分比等属于内部 event/message 字段，不新增状态枚举。

## 5. 本地模型合同

| 能力 | 模型 | 修订/要求 | 必需性 |
| --- | --- | --- | --- |
| LLM/VLM | Qwen3.6-35B-A3B GGUF Q4_K_M + BF16 mmproj | ModelScope `ggml-org/Qwen3.6-35B-A3B-GGUF`，revision `37b9ed4...`；CUDA llama.cpp `76f46ad...` | required |
| 图片编辑 | Step1X-Edit-v1p2 | `stepfun-ai/Step1X-Edit-v1p2`，revision `ca85b97...`；FP8 layerwise、默认全 GPU | required |
| T2I 辅助 | Cosmos-Predict2 0.6B Text2Image | optional pure T2I；不能作为视频依赖 | optional |
| 视频 | Cosmos3-Edge + Wan2.2 VAE | revision `6f58f6...`；Cosmos Framework `ed8287f...`；Wan VAE `921dbaf...` | required |
| ASR | Nemotron ASR | revision `f3d333391852ba876df169dcc9ba902d25b6ab0b` | required |
| TTS | Magpie TTS Multilingual 357M | revision `34d7e40da85cabc97f92198889b65cea27bc7fd1` | required |
| TTS 解码依赖 | NeMo NanoCodec + ByT5 tokenizer | NanoCodec `3c482a4...`、ByT5 `68377bd...` | required |
| 媒体 | ffmpeg/ffprobe | 本机二进制 | required |

主链路不使用 ComfyUI、OpenClaw、云端 LLM、云端图像、云端语音或云端视频 API。

## 6. ModelManager 与统一内存

ModelManager 是重型模型访问边界。它把 Qwen3.6、Step1X、Cosmos3-Edge、Magpie TTS、Nemotron ASR 的调用串行化，避免多个大模型同时常驻 DGX Spark 统一内存。连续 LLM 阶段复用同一个本地 llama.cpp 进程；进入图片、视频或音频阶段前停止 LLM，重型 adapter 退出后释放 CUDA context。

| 规则 | 要求 |
| --- | --- |
| 串行重型模型 | 同一时刻只允许一个 heavy model adapter active |
| 命令边界 | command adapter 从 stdin 读 JSON；最后一行 stdout 必须是结果 JSON，前置 NeMo 日志允许存在 |
| 失败处理 | 非零退出、非 JSON、schema 不符均计为阶段失败 |
| 残留清理 | 阶段结束后不得留下未回收模型子进程 |
| 证据记录 | manifest/qc 记录模型 id、revision、路径、耗时、重试和离线标记 |

## 7. API v1 合同

只把已实现/批准的 API 当作当前合同。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 健康检查 |
| `GET` | `/api/v1/models` | 模型清单和可用性 |
| `POST` | `/api/v1/transcriptions` | 上传音频并返回 ASR 结果 |
| `POST` | `/api/v1/campaigns` | multipart 创建 campaign，并进入 `queued` |
| `GET` | `/api/v1/campaigns` | campaign 列表 |
| `GET` | `/api/v1/campaigns/{id}` | campaign 详情、阶段、artifacts、events |
| `GET` | `/api/v1/campaigns/{id}/events` | Server-Sent Events |
| `POST` | `/api/v1/campaigns/{id}/rerun` | 从第一阶段重跑 |
| `POST` | `/api/v1/campaigns/{id}/rerun/{stage}` | 从指定阶段重跑，stage 为六阶段枚举 |
| `POST` | `/api/v1/campaigns/{id}/cancel` | 取消 campaign |
| `GET` | `/api/v1/campaigns/{id}/export` | 下载导出 ZIP |

SSE 用于呈现进度和日志，可包含 campaign/stage 状态变化、内部模型加载消息、artifact 写入消息、错误消息和完成消息。SSE event 名称是可观测事件，不是状态枚举来源。

## 8. 前端与部署

### 8.1 服务形态

批准合同是 FastAPI 在 `127.0.0.1:8000` 提供 API，并从 `runtime/frontend-dist` 服务生产前端静态资源。外部访问通过 SSH tunnel 暴露本地端口，不把 DGX Spark 服务绑定到公网网卡。

```bash
cd /home/Developer/overseaark
cp .env.example .env
./overseaark start
```

`start` 必须是幂等一键入口：依赖缺失时自动 bootstrap，必需模型缺失、尺寸错误或 SHA256 不匹配时自动断点续传修复，然后构建前端、启动本地 LLM 和 FastAPI，并通过健康检查。安装必须使用 TUNA PyPI 镜像；模型按清单优先走 ModelScope，NVIDIA 音频模型通过固定 revision 的 Hugging Face 下载，并以 `https://hf-mirror.com` 加速。`bootstrap` 和 `models sync` 保留为显式运维命令。

开发/烟测模式允许跳过重型模型：

```bash
OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark bootstrap
OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark start
```

SSH tunnel 示例：

```bash
ssh -p 6105 -L 8000:127.0.0.1:8000 root@106.13.186.155
```

打开 `http://127.0.0.1:8000` 使用前端，API base 为 `http://127.0.0.1:8000/api/v1`。

### 8.2 工作台

前端第一屏就是工作台：上传产品图、填写描述、选择 source_market/target_markets/languages、查看六阶段进度、接收 SSE 日志、预览 artifacts、执行 rerun/cancel/export。

## 9. 输入输出

| 类型 | 字段/文件 | 要求 |
| --- | --- | --- |
| 产品图片 | `product_image` | multipart；JPEG/PNG/WebP；最大 20MB |
| 描述 | `description` | 5-2000 字符 |
| 语言 | `languages` | 固定 `zh,en,ja`，默认全选 |
| 市场 | `source_market`, `target_markets` | 默认 CN 到 US/JP |
| 数据库 | `/home/Developer/overseaark-data/overseaark.sqlite3` | campaign、stage、event、artifact 元数据 |
| 上传 | `/home/Developer/overseaark-data/uploads` | 原始输入 |
| 产物 | `/home/Developer/overseaark-data/artifacts/{campaign_id}` | 阶段输出和导出 ZIP |

## 10. 失败、重试与 partial

每个阶段最多两次尝试：首次执行失败后重试一次；第二次尝试仍失败后，该阶段为 `failed`，后续未执行阶段为 `skipped`。如果此前已有有效 artifacts，campaign 必须进入 `partial` 并保留已有输出；如果没有可用输出，campaign 进入 `failed`。

取消由 `/api/v1/campaigns/{id}/cancel` 触发。取消后 campaign 为 `cancelled`，未完成阶段为 `skipped` 或保持已记录状态，已有 artifacts 不删除。

降级只作为 artifact quality 或 event message 表达，例如 `quality: "partial"` 或 `quality: "degraded"`；不得新增 campaign/stage 状态，也不得把 mock 或占位产物标为最终模型验证结果。

## 11. 隐私与离线

离线定义：从创建 campaign 到终态期间，主生成链路不得向公网发起请求。允许访问 localhost、Unix socket、本机文件、SQLite、ffmpeg 子进程和 `/home/Developer/overseaark-models`。

隐私要求：

1. 上传图、描述、中间文件和结果默认只保存在 `/home/Developer/overseaark-data`。
2. 服务只监听 `127.0.0.1`，远程使用 SSH 隧道；不开放 LAN 明文鉴权面。
3. 推理进程固定 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，LLM 地址必须是 localhost。
4. 导出包必须包含 manifest，记录模型版本、路径、重试、quality 标记和离线审计结论。
5. 日志不得主动记录密钥；API key 只存于本地 data/run 目录。

## 12. 验收标准

| 编号 | 验收项 | 标准 |
| --- | --- | --- |
| AT-001 | 三次完整运行 | 连续 3 个 campaign 在 DGX Spark 上达到 `completed`，每次 <= 10 分钟 |
| AT-002 | 三语言输出 | `multilingual_copy` 覆盖 zh/en/ja，且导出包保留三语内容 |
| AT-003 | ASR/TTS 测试 | Magpie TTS 生成三语音频，Nemotron ASR 可回读 |
| AT-004 | ASR 相似度 | ASR 回读文本与 TTS 输入相似度 >= 0.75 |
| AT-005 | 视频验收 | `campaign_video.mp4` 至少 480p，ffprobe 可读 |
| AT-006 | 重试与 partial | 注入阶段失败后第二次尝试仍失败，campaign 为 `partial`，已有输出保留 |
| AT-007 | Cosmos 失败语义 | 若使用 ffmpeg 兜底，必须明确 `degraded` 且不得冒充真模型成功 |
| AT-008 | OOM 与残留 | 三次完整运行后无 OOM、无模型子进程残留 |
| AT-009 | 离线审计 | 主生成链路公网请求数为 0 |
| AT-010 | API 契约 | `/api/v1` 路由、状态枚举和 SSE 可被 e2e 测试验证 |

截至 2026-07-22 的实机证据：五轮真模型 Campaign 均达到 `completed`；第四轮六阶段全部一次成功，用时 `590.002615s`，成为首次低于 10 分钟的完整流程。第五轮因中文语音质检重试用时 `604.844162s`，因此 AT-001 需重新获得三轮连续达标证据，本 PRD 不将单轮达标表述为已完成三轮验收。

## 13. 竞赛评分映射与结论

| 评分维度 | v1.1 证据 |
| --- | --- |
| 实用性/落地 | 外贸素材生产是高频任务，离线本地化解决数据主权与成本问题 |
| Agent 与模型深度 | 六阶段 pipeline、重型模型串行 ModelManager、ASR/TTS/视频/图像/LLM 协作 |
| 项目完整性 | frontend、backend、scripts、docs、tests/e2e、runtime/frontend-dist、root lifecycle |
| 平台适配 | DGX Spark 统一内存和本地模型目录是核心运行假设 |
| 演示效果 | 一次输入产生三语文案、视觉图、480p 视频、语音、QC 和 ZIP |

v1.1 的产品合同已经收敛为可测试的本地系统：固定目录、固定阶段、固定 API、固定状态、固定模型路径和固定验收标准。实现借鉴了赛事 workshop 的环境自检、进程管理、健康轮询和统一内存释放思路，但明确拒绝其 Ollama、OpenClaw、ComfyUI 以及 LAN 明文入口；后续实现或演示不得引入云端生成链路。
