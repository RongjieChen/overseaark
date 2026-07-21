# Competition Notes

OverseaArk's competition claim is a local DGX Spark campaign factory for cross-border sellers: one product image in, localized multimodal campaign package out, with data locality and model provenance.

## Demo Narrative

1. Connect to DGX Spark through a localhost SSH tunnel.
2. Open `http://127.0.0.1:8000`.
3. Submit one product image and one product description.
4. Watch six serialized stages: positioning, persona, copy, visual, media, packaging.
5. Export a zip with manifest, source image, localized copy, poster, narration audio, composed campaign video, and QC report.

If a model path or adapter fails, the product must show `partial` or `degraded` evidence instead of claiming final success.

## Implemented Evidence

- Single monorepo: backend, frontend, scripts, tests, and model manifest.
- No Docker, ComfyUI, OpenClaw, Ollama, or cloud inference dependency in the production path.
- Root `./overseaark start` handles dependency repair, locked model verification, missing/corrupt model download, service startup, and health check.
- FastAPI serves both `/api/v1` and the built frontend from `runtime/frontend-dist`.
- SQLite campaign state, stage state, artifacts, and event log.
- Multipart product-image upload validation.
- Six-stage campaign runner with one retry per stage.
- SSE progress stream.
- Rerun from full campaign or selected stage.
- Cancel and zip export.
- Mock mode for local rehearsals without GPU models.
- Command adapters for Qwen3.6, Step1X, Cosmos3-Edge, Nemotron ASR, and Magpie TTS.
- CUDA `llama.cpp` `llama-server` pinned to `76f46ad29d61fd8c1401e8221842934bf62a6064`.
- ModelManager serialization and LLM stop-before-heavy-adapter behavior.
- Step1X default `6` inference steps, validated by a 176.3-second DGX image benchmark.
- Cosmos3-Edge default `28` inference steps and pinned Wan2.2 VAE dependency.
- Nemotron ASR threshold check with one Magpie TTS retry per language.
- Model manifest SHA-256 verification and same-size corruption cleanup.

## DGX E2E Status

The latest status supplied for this documentation pass:

| Run | Status | Notes |
| --- | --- | --- |
| Run 1 | Completed | Completed after an intermediate fix and rerun of the affected stage. |
| Run 2 | Completed | Uninterrupted end-to-end completion in 10m34s; Japanese ASR threshold retry was exercised. |
| Run 3 | Completed | Uninterrupted completion in 10m45s; real 854x480 Cosmos output, valid zip, and ASR similarity zh `0.833`, en `1.0`, ja `1.0`. |
| Run 4 | Completed | All six stages succeeded on first attempts in 590.003s (9m50s); real 854x480 output, valid 23-member zip, and ASR similarity zh `0.933`, en `1.0`, ja `1.0`. |
| Run 5 | Completed | All stages succeeded on first attempts in 604.844s; a Chinese audio QC retry passed at `0.889`, with en `1.0` and ja `0.931`; video and 23-member zip verified. |

All five runs reached `completed`. Run 4 provides the first measured <=10-minute pass after the 6-step Step1X change. Run 5 missed by 4.844 seconds because truthful QC retried Chinese audio, so the stricter criterion now requires three new consecutive <=10-minute campaigns.

## DGX Spark Fit

- Runs local native processes on the target host.
- Binds service ports to localhost.
- Uses SSH tunneling instead of public binding.
- Keeps model weights under `/home/Developer/overseaark-models`.
- Keeps generated business data under `/home/Developer/overseaark-data`.
- Serializes heavy model calls for unified-memory pressure.
- Starts Qwen3.6 through local CUDA `llama.cpp` and stops it before non-LLM GPU adapters.
- Uses offline runtime flags during inference.
- Records model ids, revisions, licenses, stage attempts, and calls in the export manifest.

## Benchmark Evidence to Capture

| Evidence | Command | Capture |
| --- | --- | --- |
| Root health | `OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark doctor` | Pass/fail and warnings. |
| Model manifest | `./overseaark models verify` | Missing files, size mismatches, SHA-256 mismatches. |
| Backend tests | `cd backend && .venv/bin/python -m pytest` | Test count and failures. |
| Frontend tests | `cd frontend && npm test` | Test count and failures. |
| Frontend build | `cd frontend && npm run build` | Build success and output directory. |
| Mock E2E | `python3 tests/e2e/run_e2e.py --mock` | API contract pass/fail. |
| One-click lifecycle | `bash tests/e2e/test_oneclick_start.sh` | Auto-repair and safety behavior. |
| Campaign E2E | API create + SSE + export | Terminal state, runtime, zip contents. |
| LLM | `./overseaark benchmark llm` | Required JSON keys and wall time. |
| Image | `./overseaark benchmark image` | Runtime, output path, manual quality note. |
| Audio | `./overseaark benchmark audio` | Three cycles, two voices per language, ASR similarity >= 0.75. |
| Video | `./overseaark benchmark video` | Runtime, MP4 path, final/degraded label. |

## Safe Submission Language

Use:

- "Single-repo local DGX Spark campaign workbench."
- "No Docker or cloud inference path."
- "Qwen3.6-35B-A3B Q4_K_M runs through local CUDA llama.cpp."
- "Model stack is pinned by manifest with size and SHA-256 verification."
- "Step1X defaults to 6 steps and Cosmos3-Edge defaults to 28 steps for measured demo latency."
- "Nemotron ASR and Magpie TTS provide a measured audio QC loop."
- "Five real DGX E2E runs completed; run 4 completed all stages in 9m50s with a valid 480p model video and auditable export."

Avoid:

- "Three consecutive runs met the <=10 minute target"; the current evidence establishes one qualifying run.
- "Cloud-free production run" unless the specific run was audited with network controls.
- "Model quality fully validated" without benchmark logs or review notes.
- "Cosmos fallback is final output" when the adapter produced a degraded ffmpeg fallback.
- "Docker deployment" or "Ollama integration"; neither is the current path.

## Judge-facing Highlights

- The application demonstrates DGX Spark as a self-contained creative workstation rather than a proxy to hosted inference.
- The operational surface is one root command, not a notebook-only demo.
- Model acquisition is reproducible through locked source revisions, file sizes, and hashes.
- The campaign package is auditable: export includes stage payloads, QC report, model provenance, and artifacts.
- The architecture handles constrained local GPU memory by serializing model work and releasing the LLM server on demand.
