# Competition Notes

OverseaArk's competition story is a local DGX Spark campaign workbench for cross-border sellers. The value claim is data locality plus multimodal campaign packaging, not cloud automation.

## Demo Narrative

1. Connect to DGX Spark through a localhost SSH tunnel.
2. Open the app on `127.0.0.1:8000`.
3. Submit one product image and one product description.
4. Watch six stages run: positioning, persona, copy, visual, media, packaging.
5. Export a zip package with manifest, source image, generated visual, audio files, and campaign video.

If the backend or a model path is unavailable, the UI must show `partial` and `degraded` output instead of claiming success.

## Implemented Evidence

- Multipart product image upload and validation.
- Six product stages in backend and frontend.
- SQLite campaign state, stage state, and event log.
- SSE event streaming.
- Rerun from a selected stage.
- Cancel and zip export.
- Serialized model manager for heavy local model calls.
- Mock mode with deterministic image/audio/video artifacts.
- Command adapter scripts for LLM, image, video, ASR, and TTS.
- Working Step-3.7 `llama-cli` command wrapper.
- Self-healing root dispatcher: one `start` command bootstraps missing dependencies, repairs locked model files, starts the localhost service, and checks health.
- FastAPI mounts the built frontend from `runtime/frontend-dist`.
- Implemented E2E suite covers the `/api/v1` contract; mock mode currently passes 14 E2E tests.
- Adversarial lifecycle tests inject missing models, same-size SHA corruption, missing runtime dependencies, disabled repair, and repeated preflights.

## Do Not Overclaim

- Do not claim ComfyUI or OpenClaw integration. They are intentionally not in this repo path.
- Do not claim cloud inference. The runtime path is local commands and local files.
- Do not claim real model quality validation until the command adapters run on DGX Spark with target model files. Adapter implementation and DGX inference validation are separate claims.
- Do not label Cosmos fallback as final output unless validation has run. Use `degraded`.

## DGX Spark Fit

- Localhost-only service binding protects demo services.
- Unified-memory pressure is handled at the app level by serialized model calls.
- Model files live under a local model directory and are pinned by manifest.
- Mock mode lets the full app workflow run without GPU models for demo rehearsals.
- Command mode gives a narrow integration boundary for DGX-local model wrappers.

## Benchmarks to Capture

| Benchmark | Command | Report |
| --- | --- | --- |
| Root health | `OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark doctor` | Pass/fail and warnings. |
| Model manifest | `./overseaark models verify` | Missing files, size mismatches, sha256 where available. |
| Backend tests | `cd backend && .venv/bin/python -m pytest` | Test count and failures. |
| Frontend tests | `cd frontend && npm test` | Test count and failures. |
| Frontend build | `cd frontend && npm run build` | Build success and output directory. |
| E2E contract | `python3 tests/e2e/run_e2e.py --mock` | API contract pass/fail. |
| Campaign smoke | API create + SSE + export | Terminal state, runtime, zip contents. |
| ASR | Command adapter with known audio | Runtime and transcript sample. |
| TTS | Command adapter with short copy | Runtime and audible/manual check. |
| Image | Step1X adapter | Runtime, image path, manual review. |
| Video | Cosmos3 adapter | Runtime, file path, degraded/final label. |

## Suggested Submission Language

Use:

- "Local command adapter boundary implemented."
- "Mock mode validates orchestration and export packaging."
- "Model stack is pinned by manifest."
- "Step-3.7 adapter invokes local llama-cli."
- "Cosmos output is degraded unless validated."

Avoid:

- "Model quality validated" without benchmark logs.
- "Production-scale serving" without load, uptime, or deployment evidence.
- "Cloud-free production run" unless network access was disabled or audited during the demo.
