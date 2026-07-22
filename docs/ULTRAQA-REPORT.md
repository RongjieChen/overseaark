# UltraQA Report

## Goal and success criteria

- Goal: adversarially verify the one-command native DGX Spark application, six-stage campaign behavior, automatic model repair, offline adapter boundary, recovery behavior, and truthful export semantics.
- Stop condition: baseline build/tests and the hostile dynamic scenario matrix pass; discovered product defects have regression tests; temporary processes/state are cleaned; real DGX evidence is recorded without overstating the result.
- Safety bounds applied: localhost and the supplied DGX host only; no destructive repository reset, credential output, Docker, cloud inference, public bind, or unbounded process wait.
- Result: **ULTRAQA COMPLETE for the implemented native vLLM and safe-warm scope.** The current suite passes, discovered security/robustness defects have regression tests, the deployed build completed UQ-14 in 451.296 seconds, complete/scoped exports were verified, and UQ-15 proved active-TTS cancellation plus automatic worker recovery. The stricter three-consecutive-run performance criterion remains open.

## Scenario matrix

| ID | User/attacker model | Scenario | Command/harness | Expected signal | Actual result | Status | Evidence | Cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADV-E2E-001 | Normal seller | One-command mock startup, six stages, SSE, export, cancel/rerun | `./overseaark test` | All native suites pass | 84 backend, 25 frontend, 14 HTTP E2E; typecheck, build, lifecycle, and backend smoke passed | Pass | Terminal output and CI-equivalent commands below | Backend stopped by lifecycle test |
| ADV-E2E-002 | Malformed client | Wrong JSON encoding, forged image/audio bytes, empty/oversized image, unsupported path-like language | Live localhost harness plus `test_upload_boundaries.py` | 400/413/415/422; no accepted forged file | MIME and container signatures are checked; twelve upload-boundary tests pass | Pass | Dynamic harness JSON and pytest | UUID uploads isolated in temporary data dir |
| ADV-E2E-003 | Prompt-injection attacker | Chinese/Unicode prompt asks to execute shell, read `/etc/passwd`, skip QC, and claim success | Live localhost campaign plus command-adapter JSON round-trip test | Text remains inert data; no marker created | Campaign completed in mock mode; description preserved; marker absent; command adapter round-tripped exact JSON | Pass | `test_command_payload_treats_prompt_injection_as_inert_json` | Marker confirmed absent |
| ADV-E2E-004 | Repeated/interrupted user | Double cancel, cancel then rerun, rerun while already running | Live localhost harness, API and adversarial pipeline tests | Idempotent terminal state; fresh rerun completes; concurrent rerun is 409 | Double cancel stayed `cancelled`; rerun completed; active rerun returned 409 | Pass | `test_cancel_during_inflight_stage_remains_cancelled`, `test_rerun_running_campaign_returns_conflict` | No live campaign task or port remains |
| ADV-E2E-005 | Crashed backend | SQLite campaign left `running` with a running stage, then application restarts | Lifespan recovery regression test | Resume from first incomplete stage and emit recovery evidence | Initially hung indefinitely; after fix completed all six stages with `campaign.recovered` event | Pass after fix | `test_startup_resumes_campaign_left_running_by_interrupted_process` | Temporary SQLite fixture removed by pytest |
| ADV-E2E-006 | Dirty-worktree operator | Run generated QA while documentation and code edits already exist | `git status --short` before/after | No reset, masking, or unrelated overwrite | Intentional edits remained visible; only `.omx` runtime state and the documented QA temp dir were added | Pass | Worktree snapshots | `.omx` cleared through OMX state command; temp tree removed after evidence capture |
| ADV-E2E-007 | Hung CUDA adapter | Adapter and benchmark spawn a sleeping child and exceed a one-second/50-ms bound | `test_command_adapter_timeout_terminates_process_group`, `test_benchmark_timeout_terminates_child_process_group` | Parent and child process group terminate; non-success raised | Both tests passed; no child remained after bounded poll | Pass | Backend tests | Pytest temporary processes and fixtures cleaned |
| ADV-E2E-008 | Flaky scheduler | Repeat concurrency, SSE, upload, export, cancel, timeout, and recovery scenarios | 3 consecutive targeted pytest cycles | Identical green result in every cycle | 21/21 passed in 2.48s, 2.54s, and 2.54s | Pass | Three-cycle terminal output | No persistent test service |
| ADV-E2E-009 | Misleading adapter | Command prints `{"status":"SUCCESS"}` then exits 7 | `test_command_protocol_rejects_success_looking_output_with_nonzero_exit` | Exit code wins over success-looking stdout | `AdapterError` raised from stderr; stdout was not trusted | Pass | Command protocol regression test | Temporary script removed by pytest |
| ADV-E2E-010 | Resource-contention user | Two campaigns overlap; ASR always fails; Cosmos returns labeled fallback | `test_adversarial_pipeline.py` | At most one model call active; failure becomes `partial`; degraded video never becomes complete | Max active calls = 1; ASR exhausted retry and became partial; degraded Cosmos blocked completion | Pass | Five adversarial pipeline tests | Temporary artifact roots removed by pytest |
| ADV-E2E-011 | Real DGX operator | Five complete real-model campaigns; verify 480p video, audio QC, export integrity and process release | DGX API, `ffprobe`, zip integrity, SHA-256 capture | Real outputs are valid and timings are reported honestly | Five campaigns completed; run 4 was 590.003s; run 5 was 604.844s after one Chinese QC retry; valid 854x480 H.264/AAC and 23-member zips, no degraded output | Pass; one sub-10 run | Evidence directory and DGX campaign JSON | LLM stopped before heavy adapters; only FastAPI remained |
| ADV-E2E-012 | Consecutive real-run operator | Start a new campaign after the prior campaign unloaded the old LLM server | DGX run 6 plus inherited-stdout regression test | LLM control returns after daemon launch and the adapter request begins | Real run exposed a healthy old LLM server with stage still waiting for pipe EOF; temporary-file control output fix makes the inherited-stdout test return in <0.75s | Pass after fix | `test_llm_control_returns_when_daemon_inherits_standard_output` | Stuck campaign is cancelled before backend restart |
| ADV-E2E-013 | vLLM migration operator | Native vLLM 0.25.1 Campaign on `nvidia/Qwen3.6-35B-A3B-NVFP4` | DGX runs 8 and 9 | Full Campaign reaches terminal `completed`, outputs verify, and failure stays truthful | Run8 stayed `partial` on low Chinese QC; speech-native prompt fix applied; Run9 completed all stages once in `580.147s` | Pass after fix | Campaign JSON, ffprobe, ZIP integrity, SHA-256, model manifest | vLLM and all heavy adapters stopped; only FastAPI and unrelated desktop process remained |
| ADV-E2E-014 | Malicious local adapter | Adapter returns an outside path or an in-tree symlink to a secret outside the Campaign directory | Hostile hook plus `test_export_security.py` | Outside files are never read by QC or copied into ZIP | Reproduced disclosure before fix; resolved-path boundary rejects direct and symlink escape before read/export | Pass after fix | Six export/partial security regressions | Temporary secret and Campaign tree removed by pytest |
| ADV-E2E-015 | Constrained-network operator | CUDA dependency bootstrap bypasses configured mirror | Static lifecycle contract and mirror probes | TUNA remains primary PyPI; CUDA PyTorch uses configured reachable mirror | Three PyTorch installs now use `OVERSEAARK_PYTORCH_INDEX`; default corrected to reachable Aliyun cu130 | Pass after fix | Runtime contract tests and HTTP 200 mirror probe | No package state changed by probe |
| ADV-E2E-016 | Real safe-warm DGX operator | Complete zh/en/ja Campaign while ASR/TTS remain resident and heavy visual models load on demand | Deployed API Campaign `95e8efa8-7dbd-4285-b05a-8db54429d340`, assets, four exports, model/PID snapshots, and log scan | Six stages succeed; QC >=0.75; scoped exports do not leak languages; resident PIDs do not churn; no OOM/CUDA/137 | Completed in `451.296s`; all six stages passed on attempt 1; zh/en/ja `0.8333`/`1.0`/`0.88`; all four ZIPs passed; ASR/TTS stayed at starts `1`; error scan `0` | Pass | `/tmp/uq14_evidence_95e8efa8-7dbd-4285-b05a-8db54429d340` on DGX plus values below | Completion evidence captured before the dedicated Campaign was reused for UQ-15 |
| ADV-E2E-017 | Interrupting DGX operator | Cancel only after the resident TTS worker is demonstrably executing, then verify cleanup and safe-warm recovery | Media-only rerun, `/proc/<pid>/stat` activity trigger, cancel API, PID/start-count and orphan-process assertions | Old TTS process dies; new ready worker has different PID and incremented starts; early artifacts remain; later stages skip; ASR survives; health returns ready | CPU ticks rose `2336 -> 2339` with vLLM absent; old PID `3387744` died; PID `3442143` returned at starts `2`; ASR PID/starts unchanged; no heavy orphan or recent OOM/CUDA/137 | Pass | `/tmp/uq15_evidence_95e8efa8-7dbd-4285-b05a-8db54429d340` on DGX plus values below | Service intentionally left running and ready; cancelled Campaign retained as audit history |

## Commands run

- `[0] OVERSEAARK_ADAPTER_MODE=mock OVERSEAARK_MOCK_MODE=1 OVERSEAARK_SKIP_MODELS=1 ./overseaark test` — current full baseline: backend 84, frontend 25, TypeScript/Vite build, one-click corrupt/missing-model lifecycle, backend smoke, and HTTP E2E 14 all passed.
- `[0] backend/.venv/bin/python -m compileall -q backend/app backend/tests` — Python static import/compile check; Ruff was not installed and no dependency was added solely for QA.
- `[0] backend/.venv/bin/python -m pytest ...` repeated three times — 21 targeted adversarial tests passed in all three cycles.
- `[0] localhost:18080 hostile HTTP harness` — malformed body, forged image, unsupported language, prompt injection, hostile SSE cursor, repeated cancel, and cancel/rerun all produced expected results.
- `[1] first localhost harness attempt` — connection refused because the service process was launched in a completed execution session. Classified as harness apparatus failure; rerun kept startup and probes in one bounded session and passed.
- `[0] DOCX a11y and table geometry audits` — 0 accessibility findings; all 16 tables matched width, indent, grid, cell, repeated-header, and non-splitting row geometry.
- `[0] OVERSEAARK_STEP1X_STEPS=6 ./overseaark benchmark image` on DGX — 176.305 seconds, FP8 layerwise, full GPU, usable poster.
- `[0] ffprobe/zip/SHA-256 verification for runs 3 and 4` — 15-second 854x480 H.264/AAC videos and structurally valid export zips.
- `[0] native vLLM Run9 DGX verification` — 580.147-second completed Campaign; 15-second 854x480 H.264/AAC; 23-member ZIP; three SHA-256 captures; all six stage attempts equal 1.
- `[0] DGX focused post-fix tests` — 23/23 export, upload, and native vLLM runtime contract tests passed on the target machine.
- `[0] deployed UQ-14 real Campaign` — completed all six stages in 451.296 seconds; all attempts were 1; seven asset endpoints returned 200; full and zh/en/ja ZIPs passed `ZipFile.testzip()` and language isolation; resident ASR/TTS PIDs and start counts were unchanged.
- `[0] deployed UQ-15 active-TTS cancellation` — waited for the resident TTS process CPU ticks to advance with vLLM absent, cancelled, verified the old process died, then waited for safe-warm to return a new ready TTS worker with `starts=2`; health remained `ok` and no heavy-process orphan remained.

## Failures found

- ADV-E2E-005: a backend interruption could leave `queued` or `running` campaigns permanently non-terminal because startup did not reschedule persisted work. Impact: the UI could reconnect forever without progress and the operator had no API path to rerun a campaign still marked running.
- ADV-E2E-012: after a completed campaign unloaded the old LLM server, the next LLM control process could exit successfully while its daemon briefly retained captured pipe descriptors. `communicate()` then waited for daemon EOF and the first stage never sent its LLM request.
- Native vLLM cold-cache startup initially let FlashInfer compile many SM121 kernels concurrently; two `nvcc` children were killed with code 137 while model weights occupied unified memory.
- ADV-E2E-014: a compromised adapter could return an arbitrary readable host path, or a Campaign-local symlink to it, and the exporter would copy the outside bytes under a safe ZIP member name.
- ADV-E2E-002 extension: transcription accepted arbitrary bytes carrying an allowed audio MIME type and passed them to the ASR adapter.
- Bootstrap robustness: three CUDA PyTorch installs ignored `OVERSEAARK_PYTORCH_INDEX` and used a hard-coded upstream URL; the previous default mirror path also targeted cu129 while the runtime uses cu130.
- Harness apparatus: the first live HTTP probe separated service startup and test into different managed command sessions; the desktop executor cleaned the child process when the first session ended. This did not exercise product behavior and was rerun correctly in a single bounded session.
- Performance evidence: real runs 2 and 3 exceeded the <=10-minute target by 34 and 45 seconds. Run 4 subsequently passed at 590.003 seconds; the report still does not claim the stricter three-consecutive-run criterion.
- UQ-15 harness timing: the first cancellation attempt happened while the media stage was still stopping vLLM, before the TTS request began. Campaign cancellation behaved correctly, but that attempt could not prove TTS process cleanup. The test was rerun with a `/proc` CPU-tick trigger; only the second, active-worker attempt is counted as the process-cleanup proof.

## Fixes applied

- `backend/app/main.py`: on application lifespan startup, find persisted `queued`/`running` campaigns, reset only from the first incomplete stage, emit `campaign.recovered`, and reschedule through the same serialized ModelManager.
- `backend/app/store.py`: allow recovery to record a distinct event instead of masquerading as a user-triggered rerun.
- `backend/tests/test_api.py`: reproduce and lock restart recovery.
- `backend/tests/test_command_adapter_protocol.py`: lock inert JSON prompt handling and non-zero exit precedence over misleading stdout.
- `backend/app/main.py` plus `test_upload_boundaries.py`: validate product image magic bytes as well as multipart MIME type and retain streaming size enforcement.
- `scripts/adapters/image_step1x.py` and docs: move the measured demo default from 8 to 6 steps after a DGX benchmark retained usable output and saved about 45 seconds.
- `backend/app/models.py`: expose `model_status=ready` in health so the UI does not show a misleading `Model unknown` after verified startup.
- `backend/app/adapters.py`: capture LLM control output in a seekable temporary file and wait for the control PID, so a daemonized old LLM server could not extend control-command lifetime through inherited pipes.
- `backend/tests/test_command_adapter_protocol.py`: reproduce the inherited-stdout daemon case with a bounded 60-second child and verify the control call returns in under 0.75 seconds.
- `scripts/vllm_server.sh`: put vLLM/ninja/CUDA tools on the daemon PATH and serialize FlashInfer/CMake JIT with `MAX_JOBS=1`; the repaired cold-cache start reached health in 526 seconds.
- `backend/app/pipeline.py` plus `test_export_security.py`: resolve every adapter artifact before QC/export and require it to remain under the current Campaign directory, including symlink targets.
- `backend/app/main.py` plus `test_upload_boundaries.py`: validate WAV, MP3, M4A, and WebM container signatures against the declared MIME type.
- `scripts/bootstrap.sh` and `scripts/lib/common.sh`: keep TUNA as primary pip index and route CUDA PyTorch through the configurable Aliyun cu130 mirror.
- `scripts/adapters/llm_step.py`: require Chinese/Japanese video scripts to expand Latin abbreviations into pronounceable local-language text; Run9 then passed all ASR checks without retry.
- No code change was needed for UQ-15: the active-worker trigger confirmed the existing resident-adapter cancellation path terminates the worker process group and safe-warm recreates it.

## Cleanup and rollback

- The live localhost QA backend was stopped and port 18080 was confirmed unused.
- Prompt-injection marker creation was checked and remained absent.
- Pytest-managed scripts, process trees, databases, uploads, and artifacts were temporary and removed by their fixtures.
- The first failed harness left no product edit and was rerun with corrected process lifetime.
- `.omx` UltraQA state is cleared with `omx state clear`, not by deleting runtime state manually.
- Intentional source, tests, documentation, DOCX, and this report remain tracked.
- UQ-14 completion evidence was captured before its dedicated QA Campaign was intentionally reused for UQ-15. Its event history and `/tmp/uq14_evidence_*` snapshot remain on the DGX; the final live Campaign state is truthfully `cancelled` after the media-only adversarial rerun.
- The deployed service remains bound to `127.0.0.1:8000`, with vLLM prewarmed and ASR/TTS workers ready. No Step1X/Cosmos child was left after cancellation.

## Residual risks

- Native vLLM Run9 and UQ-14 independently met the <=10-minute full-flow target at 580.147 and 451.296 seconds. They do not establish a three-consecutive-run series on the exact current build, so the strict PRD performance criterion remains open.
- Runtime network isolation is enforced by offline environment variables and localhost URL validation, but no kernel-level packet-capture audit was run during the supplied real campaign.
- Real image/video quality remains sample-dependent; the automated contract verifies provenance, file validity, fallback labeling, and audio similarity rather than subjective brand quality.
- Ruff is configured but was not installed in the local test venv; `compileall`, pytest, TypeScript type checking, and Vite build were used without adding a new dependency.

## Evidence

- Real run 3 campaign: `be57ab07-a409-48bb-a65f-6ca897a7bf7d`, created `2026-07-21T20:16:01.876Z`, completed `20:26:47.261Z`.
- Run 3 output: 854x480 H.264 at 24 fps, AAC audio, 15.0 seconds; zip integrity passed.
- Run 3 ASR/TTS similarity: zh `0.833333`, en `1.0`, ja `1.0`; all >= `0.75`.
- Run 3 real model timings: Step1X 221.071s; Cosmos3-Edge 184.875s; no degraded fallback.
- Real run 4 campaign: `f1a53376-b597-4dff-8d72-2a24e371c948`, created `2026-07-21T20:54:19.972Z`, completed `21:04:09.975Z`, total `590.002615s`.
- Run 4 output: 854x480 H.264/AAC, 15.0 seconds; 23-member zip integrity passed; no degraded fallback.
- Run 4 ASR/TTS similarity: zh `0.933333`, en `1.0`, ja `1.0`; no retries.
- Run 4 real model timings: Step1X 212.667s; Cosmos3-Edge 182.057s.
- Real run 5 campaign: `f98b745b-9e43-4cc9-aac2-c7105733ecf0`, total `604.844162s`; Chinese QC retried once and passed at `0.888889`, en `1.0`, ja `0.931034`; 23-member zip valid.
- 6-step Step1X benchmark: `20260721T204232Z-image`, 176.305s, `fp8_layerwise=true`, `cpu_offload=false`.
- Native vLLM Run8 campaign: `3625def8-89e8-41d3-8b45-b51ec3a77c8a`; Qwen, Step1X, Magpie, and Cosmos succeeded, but Chinese ASR remained below threshold after automatic and operator reruns, so terminal status stayed `partial`.
- Native vLLM Run9 campaign: `ff6e7e84-45e5-4dc8-9ef9-0e2ebe30ad7e`, created `2026-07-21T23:13:26.135838Z`, completed `23:23:06.283057Z`, total `580.147219s`; all six stages succeeded on first attempts.
- Run9 ASR/TTS similarity: zh `0.9375`, en `1.0`, ja `0.9189189`; no retries.
- Run9 output: 15.0-second 854x480 at 24 fps, H.264/AAC; valid 23-member ZIP; no degraded fallback.
- Run9 SHA-256: poster `e23fec9282a66f35af7582c53906f0a9321712104e33d2821a057379c61b11fe`; video `949f242aa6ddc1a74960636d7b38c5e65d919535a397c4f7dc72072bb11d320d`; ZIP `c8f5d3fefdea3334aed9f7c11f464fb7561303d9684a889bbf4033eb62301efc`.
- UQ-14 campaign `95e8efa8-7dbd-4285-b05a-8db54429d340`: created `2026-07-22T08:50:58.268919Z`, completed `08:58:29.564934Z`, total `451.296015s`; all six stages succeeded on attempt 1.
- UQ-14 stage durations: market `5.395s`, persona `10.906s`, multilingual copy `18.046s`, Step1X `215.874s`, media `195.465s`, packaging `5.526s`.
- UQ-14 audio similarity: zh `0.833333`, en `1.0`, ja `0.88`, all with zero retry; Cosmos video quality `standard`, offline inference `true`.
- UQ-14 exports: full `8,688,765` bytes, zh `4,995,999`, en `7,768,347`, ja `4,986,145`; all four had `testzip=null`, and scoped archives contained only their requested language metadata/assets.
- UQ-14 residency: ASR PID `3387194`/starts `1` and TTS PID `3387744`/starts `1` were identical before and after the full Campaign; campaign-window backend and LLM scans found zero OOM/CUDA/137/error matches.
- UQ-15 active cancellation: TTS CPU ticks advanced `2336 -> 2339` with zero vLLM serve process at the trigger; old PID `3387744` terminated, new ready PID `3442143` returned with starts `2`, ASR remained PID `3387194`/starts `1`, health was `ok`, warmup was `ready`, and heavy-orphan scan was empty.
- PRD v2.0 verification: every page of the final font-compatible render was visually inspected with correct Chinese glyphs and clean pagination; DOCX a11y findings 0; 16/16 tables passed geometry audit.
