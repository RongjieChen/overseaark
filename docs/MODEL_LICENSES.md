# Model Licenses and Attribution

This file records model attribution for OverseaArk. It is not a repository software license and does not create a code `LICENSE` file.

Metadata was checked on 2026-07-21 from Hugging Face/API metadata and the repository's `model-manifest.lock.json`. Re-check upstream licenses before public release.

## Model Manifest

| Use | Source | Revision | Local directory | Required | Terms |
| --- | --- | --- | --- | --- | --- |
| LLM/VLM | `stepfun-ai/Step-3.7-Flash-GGUF` | `0b69336d2fd2adfdef9c66e425f7778196c31482` | `stepfun/step-3.7-flash` | yes | Apache-2.0 |
| Image | `stepfun-ai/Step1X-Edit-v1p2` | `ca85b97fd19f2235dc0d6fd3633d1319f169e149` | `stepfun/step1x-edit-v1p2` | yes | Apache-2.0 |
| Optional inspiration T2I | `nv-community/Cosmos-Predict2-0.6B-Text2Image` mirror of `nvidia/Cosmos-Predict2-0.6B-Text2Image` | ModelScope `master`, upstream `dd55b6858b22ad569976bff207880b8fea839da7` | `nvidia/cosmos-predict2-0.6b-text2image` | no | NVIDIA Open Model License |
| Video | `nv-community/Cosmos3-Edge` mirror of `nvidia/Cosmos3-Edge` | ModelScope `master`, upstream `6f58f6b4c91288838e60b6bcb2cc45d997e961de` | `nvidia/cosmos3-edge` | yes | NVIDIA Open Model Development Weight License 1.1 |
| ASR | `nvidia/nemotron-3.5-asr-streaming-0.6b` | `f3d333391852ba876df169dcc9ba902d25b6ab0b` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | yes | NVIDIA Open Model Development Weight License 1.1 |
| TTS | `nvidia/magpie_tts_multilingual_357m` | `34d7e40da85cabc97f92198889b65cea27bc7fd1` | `nvidia/magpie_tts_multilingual_357m` | yes | NVIDIA Open Model License |

## Source Links

- Step-3.7-Flash: https://huggingface.co/stepfun-ai/Step-3.7-Flash
- Step-3.7-Flash GGUF: https://huggingface.co/stepfun-ai/Step-3.7-Flash-GGUF
- Nemotron 3.5 ASR Streaming 0.6B: https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b
- Magpie TTS Multilingual 357M: https://huggingface.co/nvidia/magpie_tts_multilingual_357m
- Cosmos3-Edge: https://huggingface.co/nvidia/Cosmos3-Edge
- NVIDIA Open Model License Agreement: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/
- Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0

## Pinned Files

Selected required files from `model-manifest.lock.json`:

| Model | File | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Step-3.7 GGUF | `Q3_K_M/Step-3.7-flash-Q3_K_M-00001-of-00003.gguf` | `46768409504` | `1f79f2c30fbbc10cd180589288e0a047b72fc56a27fd7d85444f70351bd9521d` |
| Step-3.7 GGUF | `Q3_K_M/Step-3.7-flash-Q3_K_M-00002-of-00003.gguf` | `46381975392` | `c0bd348948b5c15316a54c6880d5868e5643066c930bc91045a309e9dd359618` |
| Step-3.7 GGUF | `Q3_K_M/Step-3.7-flash-Q3_K_M-00003-of-00003.gguf` | `651059456` | `65ab284b7c0cf8a6ba45dd0b0d0b354625f2a58a487c0210fc14e4002d87f833` |
| Step-3.7 GGUF | `mmproj-step3.7-flash-f16.gguf` | `3972828768` | `5f25d11f92235c69682ca820af5f4cb125ae1142c8c33c018d0b3c9000a2ec1c` |
| Step1X | `transformer/diffusion_pytorch_model-00001-of-00003.safetensors` | `9978548592` | `4c43a9758a7347e1e3c6815dd8b042a4cb24ad1df882c86be17c66a2659bbbb3` |
| Step1X | `vae/diffusion_pytorch_model.safetensors` | `335306212` | `f4487eaa8df19a5254ce83a01d402e93d2b6acba769ed9bfeddc6849cd808745` |
| Cosmos3-Edge | `transformer/diffusion_pytorch_model-00001-of-00002.safetensors` | `5000039696` | `f74b228d29f844a58bef266f3afc2d695fdc7e00f0d18b618f5889966586891b` |
| Cosmos3-Edge | `vae/diffusion_pytorch_model.safetensors` | `1409400600` | `230496cb59ff85bc9c040487737c4062480cb61c71e697b197b4c30142f2a0da` |
| Nemotron ASR | `nemotron-3.5-asr-streaming-0.6b.nemo` | `2368284501` | `210214ed94039bf6bfbb9a047c7fa289628db75b103e2bf6381fa78285436a74` |
| Magpie TTS | `magpie_tts_multilingual_357m.nemo` | `1208883200` | `3111c41d88de500dbc0cee70802c0ae7fb54915c46f29a2391a4510081f76a94` |

The manifest contains additional required Step1X, Cosmos-Predict2, and Cosmos3 files with sizes and SHA-256 hashes. Treat `model-manifest.lock.json` as the source of truth for verification.

## Framework Pins

| Framework | Commit |
| --- | --- |
| Peyton-Chen/diffusers `step1xedit_v1p2` | `f5f1c98fa00cb4d0479af1b1b1c17d724345963a` |
| NVIDIA/cosmos-framework | `ed8287fd7477113f8ac4f6b84290514d55cf0cdc` |
| NVIDIA-NeMo/NeMo | `93b15b1f423ddc8e0d189810fdd8304091d9b1bd` |

## Attribution Notes

- Preserve upstream model card notices and license links in demos, reports, and redistributed artifacts.
- Do not commit model weights to this repository.
- Keep model weights under `OVERSEAARK_MODELS_DIR`.
- Do not describe mock or degraded fallback outputs as final model outputs.
- Re-check upstream model cards before publication.
