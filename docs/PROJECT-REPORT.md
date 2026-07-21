# 出海方舟 OverseaArk：在 DGX Spark 上运行的本地多模态外贸营销团队

## 项目摘要

出海方舟 OverseaArk 面向中小外贸企业、跨境卖家和代运营团队，把一张产品图和一段产品描述转换为可直接交付的完整 Campaign 素材包。系统不是调用云端大模型的网页壳，而是原生运行在 NVIDIA DGX Spark 上的本地应用：市场定位、买家画像、中英日文案、产品海报、三语配音、480p 图生视频、ASR 回听质检和 ZIP 打包全部在本机完成。产品资料、生成结果、SQLite 状态和日志均保存在用户指定的数据目录中，模型也存放在仓库外的独立目录。

项目采用一个公开 monorepo，前端、后端、模型适配器、部署脚本、测试和文档都在同一仓库。用户只需要在仓库根目录执行 `./overseaark start`。脚本会检查运行环境、构建前端、校验锁定模型、下载缺失或校验失败的文件、启动本地 CUDA llama.cpp 与 FastAPI，并等待健康检查通过。整个方案不使用 Docker、ComfyUI、OpenClaw、Ollama、StepFun 云 API 或 NVIDIA 托管推理 API；服务只监听 `127.0.0.1`，远程访问通过 SSH 隧道完成。

## 为什么要做本地外贸营销工作台

外贸营销素材通常分散在市场研究、文案翻译、视觉设计、视频制作和质量检查等多个工具里。小团队需要反复复制产品资料，交付链长且难以审计；工厂和品牌方还会顾虑尚未发布的产品图、报价资料或工艺信息被上传到外部服务。OverseaArk 把这些步骤固化为六阶段流水线，并把“模型是否真的运行”“失败是否被如实标记”“产物由哪个版本生成”等问题纳入产品合同，而不只追求一次漂亮的演示。

## 六阶段 Agent 流水线

第一阶段由 Qwen3.6-35B-A3B 生成目标市场定位、差异化卖点和待验证假设；第二阶段形成买家画像、痛点、购买动机和渠道建议；第三阶段一次性生成中文、英文和日文的标题、卖点、详情页正文、开发信和短视频脚本。前三个阶段连续复用本地 CUDA llama.cpp 服务。

第四阶段先停止 LLM 进程，释放 DGX Spark 统一内存，再由 Step1X-Edit-v1p2 直接进行产品图编辑，最后用 Pillow 排版文字。第五阶段由 NVIDIA MagpieTTS Multilingual 357M 生成中、英、日三语配音，由 NVIDIA Cosmos3-Edge 生成 480p 图生视频，并用 ffmpeg 合成字幕、配音和 MP4。第六阶段使用 NVIDIA Nemotron 3.5 ASR Streaming 0.6B 回听三条配音，计算规范化文本相似度；低于 0.75 的语言自动重做一次 TTS。最终 ZIP 包保存三语文案、海报、音频、视频、质量报告、阶段输出和模型溯源清单。

所有重型模型调用都经过单一 `ModelManager` 锁串行调度，任何时刻最多只有一个 GPU adapter 在工作。若阶段第一次失败，系统自动重试一次；第二次仍失败时 Campaign 进入 `partial`，前面成功的成果不会丢失。Cosmos 真模型失败时可以保留一个明确标记为 `degraded` 的 ffmpeg 兜底视频，但该结果不能冒充完整成功。

## 模型与工程选择

主模型采用 `ggml-org/Qwen3.6-35B-A3B-GGUF` 的 Q4_K_M 权重和 BF16 mmproj，通过固定提交的 CUDA llama.cpp 运行。GGUF 选择与本地文件格式保持一致，避免把不受 vLLM 支持的格式强行塞进不合适的推理框架。Step1X 使用 FP8 layerwise、默认全 GPU 推理；视频使用 Cosmos3-Edge 和锁定的 Wan2.2 VAE；语音识别和语音合成都使用 NVIDIA 开放权重。

模型清单记录模型 ID、来源、revision、本地目录、文件大小、SHA-256 和许可证。下载策略在生命周期阶段允许联网：StepFun 与 Cosmos 优先使用 ModelScope，Hugging Face 模型默认使用 `https://hf-mirror.com`，Python 包使用清华 TUNA 镜像。进入推理阶段后强制设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 和 `HF_DATASETS_OFFLINE=1`，并拒绝非 localhost 的模型服务地址。

## 前后端与可恢复状态

后端采用 FastAPI、Pydantic、SQLite 和本地文件系统；前端使用 Vite、TypeScript 和 SSE。FastAPI 同时托管 `/api/v1` 与构建后的前端，因此只需要一个 8000 端口。Campaign 和 Stage 使用明确状态枚举，SSE 事件带递增 sequence，客户端可从最后序号继续读取。页面通过 `?campaign=<id>` 深链和本地浏览器状态恢复当前任务；即使后端在生成中被中断，重启时也会从第一个未完成阶段恢复，并记录 `campaign.recovered` 事件。

## 实机验证与对抗性审查

项目已在指定 DGX Spark 上完成五次真实模型全流程。第一轮在中间修复后通过阶段重跑完成；第二、三轮无中断完成，分别用时 10 分 34 秒和 10 分 45 秒。将 Step1X 默认值由 8 步调整为经独立基准验证的 6 步后，第四轮六个阶段全部一次成功，端到端用时 590.003 秒（约 9 分 50 秒）。第五轮也全部一次成功，但中文语音质检触发一次内部重试，总用时 604.844 秒，比目标多 4.844 秒；最终中文、英文、日文相似度为 0.889、1.0、0.931。实测产物均为真实 Step1X/Cosmos/Magpie/Nemotron 输出，15 秒 854×480 H.264/AAC 视频和 23 文件 ZIP 通过结构校验。

除正常测试外，我们按 UltraQA 方式构造了恶意和故障场景：伪造 PNG、空文件和超大文件、路径穿越式字段、Unicode 提示注入、连续取消与重跑、两个 Campaign 同时竞争模型、SSE 断点续传、ASR 永久低相似度、Cosmos 降级伪装、adapter 超时后的子进程残留，以及输出写着 SUCCESS 但进程返回非零。审查发现并修复了两个真实问题：后端崩溃可能让 SQLite 中的运行任务永久卡住；首次从卸载状态重启 llama-server 时，后台进程继承标准输出管道可让控制命令等待错误的 EOF。修复后，完整本地套件包括 47 个后端测试、8 个前端测试和 14 个 HTTP Mock E2E。

## 结果与仍需改进的地方

OverseaArk 已证明 DGX Spark 可以作为一台自包含的多模态创意工作站，而不是云端推理的代理。它把模型能力落成了可以启动、观察、重跑、取消、恢复、质检和导出的产品流程，并通过模型清单和 ZIP manifest 提供可审计证据。

当前性能目标已有一轮实测达标。第二、三轮均成功，但分别超出“十分钟内完成”目标 34 秒和 45 秒；Step1X 的 6 步独立 DGX 基准为 176.3 秒，第四轮完整流程随后实测为 590.003 秒，证明优化在端到端场景有效。第五轮因质检重试用时 604.844 秒，打断了连续达标序列。目前只能宣称“一次实测低于十分钟”；PRD 中“连续三轮”的更严格验收标准需重新获得三轮连续达标证据。

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
