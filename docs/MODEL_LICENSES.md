# Model Licenses and Attribution

This file records model attribution for OverseaArk. It is not a repository software license and does not create a code `LICENSE` file.

Metadata was checked against `model-manifest.lock.json` on 2026-07-22. Re-check upstream model cards and license pages before public release or redistribution.

## Manifest Summary

| Use | Manifest id | Provider | Source | Revision | Local directory | Required | Terms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LLM/VLM | `qwen3.6-35b-a3b-gguf-q4_k_m` | ModelScope | `ggml-org/Qwen3.6-35B-A3B-GGUF` | `37b9ed4ed8b3942a5ac69bffb490a5d25acdad4e` | `qwen/qwen3.6-35b-a3b-gguf` | yes | Apache-2.0 |
| Image | `step1x-edit-v1p2` | Hugging Face | `stepfun-ai/Step1X-Edit-v1p2` | `ca85b97fd19f2235dc0d6fd3633d1319f169e149` | `stepfun/step1x-edit-v1p2` | yes | Apache-2.0 |
| Optional T2I | `cosmos-predict2-0.6b-text2image` | ModelScope | `nv-community/Cosmos-Predict2-0.6B-Text2Image`, mirror of `nvidia/Cosmos-Predict2-0.6B-Text2Image` | `master`, upstream `dd55b6858b22ad569976bff207880b8fea839da7` | `nvidia/cosmos-predict2-0.6b-text2image` | no | NVIDIA Open Model License |
| Video | `cosmos3-edge` | ModelScope | `nv-community/Cosmos3-Edge`, mirror of `nvidia/Cosmos3-Edge` | `master`, upstream `6f58f6b4c91288838e60b6bcb2cc45d997e961de` | `nvidia/cosmos3-edge` | yes | NVIDIA Open Model Development Weight License 1.1 |
| Video VAE | `wan2.2-vae-cosmos3` | ModelScope | `Wan-AI/Wan2.2-TI2V-5B` | `master`, upstream `921dbaf3f1674a56f47e83fb80a34bac8a8f203e` | `wan/wan2.2-vae` | yes | Apache-2.0 |
| ASR | `nemotron-asr-streaming-0.6b` | Hugging Face | `nvidia/nemotron-3.5-asr-streaming-0.6b` | `f3d333391852ba876df169dcc9ba902d25b6ab0b` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | yes | NVIDIA Open Model Development Weight License 1.1 |
| TTS codec | `nemo-nano-codec-22khz-1.89kbps-21.5fps` | Hugging Face | `nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps` | `3c482a402a3c4cf33690a2c0f0a7d41afea6bd6a` | `nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps` | yes | NVIDIA Open Model License |
| TTS | `magpie-tts-multilingual-357m` | Hugging Face | `nvidia/magpie_tts_multilingual_357m` | `34d7e40da85cabc97f92198889b65cea27bc7fd1` | `nvidia/magpie_tts_multilingual_357m` | yes | NVIDIA Open Model License |
| TTS tokenizer | `byt5-small-tokenizer` | Hugging Face | `google/byt5-small` | `68377bdc18a2ffec8a0533fef03b1c513a4dd49d` | `google/byt5-small` | yes | Apache-2.0 |

Required locked files total 79,075,769,933 bytes. Including optional Cosmos-Predict2, the manifest totals 83,399,999,524 bytes.

## Source Links

- Qwen3.6-35B-A3B-GGUF: https://modelscope.cn/models/ggml-org/Qwen3.6-35B-A3B-GGUF
- Step1X-Edit-v1p2: https://huggingface.co/stepfun-ai/Step1X-Edit-v1p2
- Cosmos-Predict2 0.6B Text2Image: https://huggingface.co/nvidia/Cosmos-Predict2-0.6B-Text2Image
- Cosmos3-Edge: https://huggingface.co/nvidia/Cosmos3-Edge
- Wan2.2-TI2V-5B: https://modelscope.cn/models/Wan-AI/Wan2.2-TI2V-5B
- Nemotron 3.5 ASR Streaming 0.6B: https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b
- NeMo NanoCodec 22kHz 1.89kbps 21.5fps: https://huggingface.co/nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps
- Magpie TTS Multilingual 357M: https://huggingface.co/nvidia/magpie_tts_multilingual_357m
- ByT5 Small: https://huggingface.co/google/byt5-small
- NVIDIA Open Model License Agreement: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/
- Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0

## Selected Pinned Files

Treat `model-manifest.lock.json` as the full verification source. Selected required files:

| Model | File | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Qwen3.6 GGUF | `Qwen3.6-35B-A3B-Q4_K_M.gguf` | `20419565568` | `671e47e0ec53c665d048b98c3ecbfd5236b5ca9c3e02ed19fc8f81f7b85140c7` |
| Qwen3.6 mmproj | `mmproj-Qwen3.6-35B-A3B-BF16.gguf` | `902822144` | `360c746ddf38fb67c06f83a0a88742492aa231e59e335cd980e6302f59ea6089` |
| Step1X | `text_encoder/model-00001-of-00004.safetensors` | `4968243304` | `f4b54b9f0b843a1837a4e3c26cee7dd62d6697a6d7592d5ca2d005914aed5591` |
| Step1X | `transformer/diffusion_pytorch_model-00001-of-00003.safetensors` | `9978548592` | `4c43a9758a7347e1e3c6815dd8b042a4cb24ad1df882c86be17c66a2659bbbb3` |
| Step1X | `vae/diffusion_pytorch_model.safetensors` | `335306212` | `f4487eaa8df19a5254ce83a01d402e93d2b6acba769ed9bfeddc6849cd808745` |
| Cosmos3-Edge | `transformer/diffusion_pytorch_model-00001-of-00002.safetensors` | `5000039696` | `f74b228d29f844a58bef266f3afc2d695fdc7e00f0d18b618f5889966586891b` |
| Cosmos3-Edge | `vae/diffusion_pytorch_model.safetensors` | `1409400600` | `230496cb59ff85bc9c040487737c4062480cb61c71e697b197b4c30142f2a0da` |
| Cosmos3-Edge | `vision_encoder/model.safetensors` | `978739880` | `2180ad739ecc96b5c1e9386892d3c5c08bfa42b9cdab9aabc53b028671db89b3` |
| Wan VAE | `Wan2.2_VAE.pth` | `2818839170` | `20eb789667fa5e60e7516bf509512f6cb61f01b0aa0695eadaea930c13892b36` |
| Nemotron ASR | `nemotron-3.5-asr-streaming-0.6b.nemo` | `2368284501` | `210214ed94039bf6bfbb9a047c7fa289628db75b103e2bf6381fa78285436a74` |
| Magpie NanoCodec | `nemo-nano-codec-22khz-1.89kbps-21.5fps.nemo` | `425021440` | `28c2518de3e3d5a2c7d9bca40a7ebc0644eb76c60b890970365325bdd8e9f099` |
| Magpie TTS | `magpie_tts_multilingual_357m.nemo` | `1208883200` | `3111c41d88de500dbc0cee70802c0ae7fb54915c46f29a2391a4510081f76a94` |

## Framework Pins

| Framework | Pin |
| --- | --- |
| `ggml-org/llama.cpp` | `76f46ad29d61fd8c1401e8221842934bf62a6064` |
| Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| NVIDIA-NeMo/NeMo for ASR | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |
| NeMo TTS | `nemo_toolkit[tts]==2.7.3` |

## Attribution Requirements

- Preserve upstream model names, model card links, and license links in demos, reports, and redistributed artifacts.
- Attribute ModelScope mirrors as mirrors when the manifest source is `nv-community/...` for NVIDIA models.
- Do not commit model weights to this repository.
- Keep model weights under `OVERSEAARK_MODELS_DIR`.
- Do not describe mock, ffmpeg degraded fallback, or frontend local preview artifacts as final model outputs.
- Re-check upstream model cards before publication because licenses and acceptable-use notices can change.
