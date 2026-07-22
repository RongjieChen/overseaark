# 出海方舟 OverseaArk：在 DGX Spark 上运行的本地多模态外贸营销团队

## 项目摘要

出海方舟 OverseaArk 面向中小外贸企业、跨境卖家和代运营团队，把一张产品图和一段产品描述转换为可直接交付的完整 Campaign 素材包。系统不是调用云端大模型的网页壳，而是原生运行在 NVIDIA DGX Spark 上的本地应用：市场定位、买家画像、中英日文案、产品海报、三语配音、480p 图生视频、ASR 回听质检和 ZIP 打包全部在本机完成。产品资料、生成结果、SQLite 状态和日志均保存在用户指定的数据目录中，模型也存放在仓库外的独立目录。

项目采用一个公开 monorepo，前端、后端、模型适配器、部署脚本、测试和文档都在同一仓库。用户只需要在仓库根目录执行 `./overseaark start`。脚本会检查运行环境、构建前端、校验锁定模型、下载缺失或校验失败的文件、安装独立 `.venv-vllm` 中的 native vLLM 0.25.1 ARM64 CUDA wheel、启动本地 vLLM 与 FastAPI，并等待健康检查通过。整个方案不使用 Docker、ComfyUI、OpenClaw、Ollama、StepFun 云 API 或 NVIDIA 托管推理 API；服务只监听 `127.0.0.1`，远程访问通过 SSH 隧道完成。

## 为什么要做本地外贸营销工作台

外贸营销素材通常分散在市场研究、文案翻译、视觉设计、视频制作和质量检查等多个工具里。小团队需要反复复制产品资料，交付链长且难以审计；工厂和品牌方还会顾虑尚未发布的产品图、报价资料或工艺信息被上传到外部服务。OverseaArk 把这些步骤固化为六阶段流水线，并把“模型是否真的运行”“失败是否被如实标记”“产物由哪个版本生成”等问题纳入产品合同，而不只追求一次漂亮的演示。

## 六阶段 Agent 流水线

第一阶段由 Qwen3.6-35B-A3B 生成目标市场定位、差异化卖点和待验证假设；第二阶段形成买家画像、痛点、购买动机和渠道建议；第三阶段一次性生成中文、英文和日文的标题、卖点、详情页正文、开发信和短视频脚本。前三个阶段连续复用本地 native vLLM 服务。

第四阶段先停止 LLM 进程，释放 DGX Spark 统一内存，再由 Step1X-Edit-v1p2 直接进行产品图编辑，最后用 Pillow 排版文字。第五阶段由 NVIDIA MagpieTTS Multilingual 357M 生成中、英、日三语配音，由 NVIDIA Cosmos3-Edge 生成 480p 图生视频，并用 ffmpeg 合成字幕、配音和 MP4。第六阶段使用 NVIDIA Nemotron 3.5 ASR Streaming 0.6B 回听三条配音，计算规范化文本相似度；低于 0.75 的语言自动重做一次 TTS。最终 ZIP 包保存三语文案、海报、音频、视频、质量报告、阶段输出和模型溯源清单。

所有重型模型调用都经过单一 `ModelManager` 锁串行调度，任何时刻最多只有一个 GPU adapter 在工作。若阶段第一次失败，系统自动重试一次；第二次仍失败时 Campaign 进入 `partial`，前面成功的成果不会丢失。Cosmos 真模型失败时可以保留一个明确标记为 `degraded` 的 ffmpeg 兜底视频，但该结果不能冒充完整成功。

## 模型与工程选择

主模型采用 `nvidia/Qwen3.6-35B-A3B-NVFP4`，固定 revision 为 `491c2f1ea524c639598bf8fa787a93fed5a6fbce`，模型文件约 23.45GB，通过 native vLLM 0.25.1 ARM64 CUDA wheel 在 `127.0.0.1:8011` 提供 OpenAI-compatible 接口。运行参数采用 DGX Spark 路径：fp8 KV cache、flashinfer attention、marlin MoE、262144 上下文、4 个序列、8192 batched tokens、chunked prefill、prefix caching 和 MTP speculative decoding。Step1X 使用 FP8 layerwise、默认全 GPU 推理；视频使用 Cosmos3-Edge 和锁定的 Wan2.2 VAE；语音识别和语音合成都使用 NVIDIA 开放权重。

模型清单记录模型 ID、来源、revision、本地目录、文件大小、SHA-256 和许可证。下载策略在生命周期阶段允许联网：Qwen3.6 NVFP4 和 NVIDIA 音频模型默认使用 `https://hf-mirror.com`，Python 包使用清华 TUNA 镜像，StepFun 与 Cosmos 继续按清单使用镜像源。进入推理阶段后强制设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 和 `HF_DATASETS_OFFLINE=1`，并拒绝非 localhost 的模型服务地址。

## 前后端与可恢复状态

后端采用 FastAPI、Pydantic、SQLite 和本地文件系统；前端使用 Vite、TypeScript 和 SSE。界面默认显示简体中文，可一键切换为英文并在浏览器中持久保存选择；切换时同步页面标题、无障碍标签、阶段状态、校验错误和前端进度消息，不改写模型生成的原始内容。FastAPI 同时托管 `/api/v1` 与构建后的前端，因此只需要一个 8000 端口。Campaign 和 Stage 使用明确状态枚举，SSE 事件带递增 sequence，客户端可从最后序号继续读取。页面通过 `?campaign=<id>` 深链和本地浏览器状态恢复当前任务；即使后端在生成中被中断，重启时也会从第一个未完成阶段恢复，并记录 `campaign.recovered` 事件。

## 实机验证与对抗性审查

项目已在指定 DGX Spark 上完成多次旧运行时与 native vLLM 真实模型全流程。旧运行时第四轮用时 590.003 秒，Run7 冷启动用时 9 分 12 秒，这些只作为历史证据。native vLLM Run8 的 Qwen、Step1X、Magpie 和 Cosmos 都完成了真实推理，但中文口播中的拉丁字母缩写导致回听相似度经重试仍低于 0.75，Campaign 被如实保留为 `partial`。将中文和日文口播改为可直接发音的本地语言后，Run9 六阶段全部一次成功，用时 580.147 秒（约 9 分 40 秒）。中、英、日回听相似度为 0.9375、1.0、0.9189，15 秒 854×480 H.264/AAC 真模型视频与 23 文件 ZIP 通过校验。

除正常测试外，我们按 UltraQA 方式构造了恶意和故障场景：伪造图片与音频、超大上传、Unicode 提示注入、连续取消与重跑、并发 Campaign、SSE 断点续传、ASR 永久低相似度、Cosmos 降级伪装、adapter 超时子进程残留、成功样式输出配合非零退出，以及恶意 adapter 用符号链接读取 Campaign 目录外文件。审查修复了中断任务恢复、旧 LLM 守护进程管道、FlashInfer 首启并行编译 OOM、adapter 产物路径越界导出和音频 MIME 伪造五类真实问题。完整本地套件现包括 84 个后端测试、25 个前端测试和 14 个 HTTP Mock E2E，另含类型检查、构建、生命周期和后端烟测。

## 结果与仍需改进的地方

OverseaArk 已证明 DGX Spark 可以作为一台自包含的多模态创意工作站，而不是云端推理的代理。它把模型能力落成了可以启动、观察、重跑、取消、恢复、质检和导出的产品流程，并通过模型清单和 ZIP manifest 提供可审计证据。

native vLLM 迁移已获得两次独立的十分钟内实机证据：Run9 用时 580.147 秒，safe-warm UQ-14 用时 451.296 秒，两次均为六阶段全部一次成功。它们证明 native vLLM 与 Step1X、Cosmos、Magpie、Nemotron 的串行切换可以在目标时间内完成，但尚未形成同一当前构建连续三次达标的完整序列，因此不宣称严格性能验收已经闭合。

## 开源仓库与启动方式

项目仓库：[RongjieChen/overseaark](https://github.com/RongjieChen/overseaark)

```bash
git clone https://github.com/RongjieChen/overseaark.git
cd overseaark
./overseaark start
```

远程访问 DGX Spark 时，将本地端口转发到服务的 localhost：

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<dgx-host>
```

模型验证、诊断、日志、测试和单项基准均通过同一个根命令完成。详细模型版本、许可证、部署说明、API 示例、故障排查、PRD 和 UltraQA 报告均已提交到仓库文档目录。
