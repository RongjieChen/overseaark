# UltraQA Report

## Goal and success criteria

- Goal: adversarially verify the one-command native DGX Spark application, six-stage campaign behavior, automatic model repair, offline adapter boundary, recovery behavior, and truthful export semantics.
- Stop condition: baseline build/tests and the hostile dynamic scenario matrix pass; discovered product defects have regression tests; temporary processes/state are cleaned; real DGX evidence is recorded without overstating the result.
- Safety bounds applied: localhost and the supplied DGX host only; no destructive repository reset, credential output, Docker, cloud inference, public bind, or unbounded process wait.
- Result: **ULTRAQA COMPLETE: goal met after 3 cycles.** Cycle 1 fixed interrupted-campaign recovery. Extended real-run cycle 3 found and fixed an LLM control-pipe lifetime defect. A separate localhost harness setup failure was corrected and was not classified as a product defect.

## Scenario matrix

| ID | User/attacker model | Scenario | Command/harness | Expected signal | Actual result | Status | Evidence | Cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADV-E2E-001 | Normal seller | One-command mock startup, six stages, SSE, export, cancel/rerun | `./overseaark test` | All native suites pass | 47 backend, 8 frontend, 14 HTTP E2E; build and lifecycle passed | Pass | Terminal output and CI-equivalent commands below | Backend stopped by lifecycle test |
| ADV-E2E-002 | Malformed client | Wrong JSON encoding, forged PNG, empty/oversized image, unsupported path-like language | Live localhost harness plus `test_upload_boundaries.py` | 400/413/415/422; no accepted forged file | Live 422/415/422; six upload boundary tests pass | Pass | Dynamic harness JSON and pytest | UUID uploads isolated in temporary data dir |
| ADV-E2E-003 | Prompt-injection attacker | Chinese/Unicode prompt asks to execute shell, read `/etc/passwd`, skip QC, and claim success | Live localhost campaign plus command-adapter JSON round-trip test | Text remains inert data; no marker created | Campaign completed in mock mode; description preserved; marker absent; command adapter round-tripped exact JSON | Pass | `test_command_payload_treats_prompt_injection_as_inert_json` | Marker confirmed absent |
| ADV-E2E-004 | Repeated/interrupted user | Double cancel, cancel then rerun, rerun while already running | Live localhost harness, API and adversarial pipeline tests | Idempotent terminal state; fresh rerun completes; concurrent rerun is 409 | Double cancel stayed `cancelled`; rerun completed; active rerun returned 409 | Pass | `test_cancel_during_inflight_stage_remains_cancelled`, `test_rerun_running_campaign_returns_conflict` | No live campaign task or port remains |
| ADV-E2E-005 | Crashed backend | SQLite campaign left `running` with a running stage, then application restarts | Lifespan recovery regression test | Resume from first incomplete stage and emit recovery evidence | Initially hung indefinitely; after fix completed all six stages with `campaign.recovered` event | Pass after fix | `test_startup_resumes_campaign_left_running_by_interrupted_process` | Temporary SQLite fixture removed by pytest |
| ADV-E2E-006 | Dirty-worktree operator | Run generated QA while documentation and code edits already exist | `git status --short` before/after | No reset, masking, or unrelated overwrite | Intentional edits remained visible; only `.omx` runtime state and the documented QA temp dir were added | Pass | Worktree snapshots | `.omx` cleared through OMX state command; temp tree removed after evidence capture |
| ADV-E2E-007 | Hung CUDA adapter | Adapter and benchmark spawn a sleeping child and exceed a one-second/50-ms bound | `test_command_adapter_timeout_terminates_process_group`, `test_benchmark_timeout_terminates_child_process_group` | Parent and child process group terminate; non-success raised | Both tests passed; no child remained after bounded poll | Pass | Backend tests | Pytest temporary processes and fixtures cleaned |
| ADV-E2E-008 | Flaky scheduler | Repeat concurrency, SSE, upload, export, cancel, timeout, and recovery scenarios | 3 consecutive targeted pytest cycles | Identical green result in every cycle | 21/21 passed in 2.48s, 2.54s, and 2.54s | Pass | Three-cycle terminal output | No persistent test service |
| ADV-E2E-009 | Misleading adapter | Command prints `{"status":"SUCCESS"}` then exits 7 | `test_command_protocol_rejects_success_looking_output_with_nonzero_exit` | Exit code wins over success-looking stdout | `AdapterError` raised from stderr; stdout was not trusted | Pass | Command protocol regression test | Temporary script removed by pytest |
| ADV-E2E-010 | Resource-contention user | Two campaigns overlap; ASR always fails; Cosmos returns labeled fallback | `test_adversarial_pipeline.py` | At most one model call active; failure becomes `partial`; degraded video never becomes complete | Max active calls = 1; ASR exhausted retry and became partial; degraded Cosmos blocked completion | Pass | Five adversarial pipeline tests | Temporary artifact roots removed by pytest |
| ADV-E2E-011 | Real DGX operator | Five complete real-model campaigns; verify 480p video, audio QC, export integrity and process release | DGX API, `ffprobe`, zip integrity, SHA-256 capture | Real outputs are valid and timings are reported honestly | Five campaigns completed; run 4 was 590.003s; run 5 was 604.844s after one Chinese QC retry; valid 854x480 H.264/AAC and 23-member zips, no degraded output | Pass; one sub-10 run | Evidence directory and DGX campaign JSON | LLM stopped before heavy adapters; only FastAPI remained |
| ADV-E2E-012 | Consecutive real-run operator | Start a new campaign after the prior campaign unloaded llama-server | DGX run 6 plus inherited-stdout regression test | LLM control returns after daemon launch and the adapter request begins | Real run exposed a healthy llama-server with stage still waiting for pipe EOF; temporary-file control output fix makes the inherited-stdout test return in <0.75s | Pass after fix | `test_llm_control_returns_when_daemon_inherits_standard_output` | Stuck campaign is cancelled before backend restart |

## Commands run

- `[0] ./overseaark test` — full baseline before the extended lifecycle fix: backend 46, frontend 8, TypeScript/Vite build, one-click lifecycle, HTTP E2E 14; the added control-pipe regression raises the backend count to 47.
- `[0] backend/.venv/bin/python -m compileall -q backend/app backend/tests` — Python static import/compile check; Ruff was not installed and no dependency was added solely for QA.
- `[0] backend/.venv/bin/python -m pytest ...` repeated three times — 21 targeted adversarial tests passed in all three cycles.
- `[0] localhost:18080 hostile HTTP harness` — malformed body, forged image, unsupported language, prompt injection, hostile SSE cursor, repeated cancel, and cancel/rerun all produced expected results.
- `[1] first localhost harness attempt` — connection refused because the service process was launched in a completed execution session. Classified as harness apparatus failure; rerun kept startup and probes in one bounded session and passed.
- `[0] DOCX a11y and table geometry audits` — 0 accessibility findings; all 14 tables matched width, indent, grid, and cell geometry.
- `[0] OVERSEAARK_STEP1X_STEPS=6 ./overseaark benchmark image` on DGX — 176.305 seconds, FP8 layerwise, full GPU, usable poster.
- `[0] ffprobe/zip/SHA-256 verification for runs 3 and 4` — 15-second 854x480 H.264/AAC videos and structurally valid export zips.

## Failures found

- ADV-E2E-005: a backend interruption could leave `queued` or `running` campaigns permanently non-terminal because startup did not reschedule persisted work. Impact: the UI could reconnect forever without progress and the operator had no API path to rerun a campaign still marked running.
- ADV-E2E-012: after a completed campaign unloaded llama-server, the next LLM control process could exit successfully while its daemon briefly retained captured pipe descriptors. `communicate()` then waited for daemon EOF and the first stage never sent its LLM request.
- Harness apparatus: the first live HTTP probe separated service startup and test into different managed command sessions; the desktop executor cleaned the child process when the first session ended. This did not exercise product behavior and was rerun correctly in a single bounded session.
- Performance evidence: real runs 2 and 3 exceeded the <=10-minute target by 34 and 45 seconds. Run 4 subsequently passed at 590.003 seconds; the report still does not claim the stricter three-consecutive-run criterion.

## Fixes applied

- `backend/app/main.py`: on application lifespan startup, find persisted `queued`/`running` campaigns, reset only from the first incomplete stage, emit `campaign.recovered`, and reschedule through the same serialized ModelManager.
- `backend/app/store.py`: allow recovery to record a distinct event instead of masquerading as a user-triggered rerun.
- `backend/tests/test_api.py`: reproduce and lock restart recovery.
- `backend/tests/test_command_adapter_protocol.py`: lock inert JSON prompt handling and non-zero exit precedence over misleading stdout.
- `backend/app/main.py` plus `test_upload_boundaries.py`: validate product image magic bytes as well as multipart MIME type and retain streaming size enforcement.
- `scripts/adapters/image_step1x.py` and docs: move the measured demo default from 8 to 6 steps after a DGX benchmark retained usable output and saved about 45 seconds.
- `backend/app/models.py`: expose `model_status=ready` in health so the UI does not show a misleading `Model unknown` after verified startup.
- `backend/app/adapters.py`: capture LLM control output in a seekable temporary file and wait for the control PID, so a daemonized llama-server cannot extend control-command lifetime through inherited pipes.
- `backend/tests/test_command_adapter_protocol.py`: reproduce the inherited-stdout daemon case with a bounded 60-second child and verify the control call returns in under 0.75 seconds.

## Cleanup and rollback

- The live localhost QA backend was stopped and port 18080 was confirmed unused.
- Prompt-injection marker creation was checked and remained absent.
- Pytest-managed scripts, process trees, databases, uploads, and artifacts were temporary and removed by their fixtures.
- The first failed harness left no product edit and was rerun with corrected process lifetime.
- `.omx` UltraQA state is cleared with `omx state clear`, not by deleting runtime state manually.
- Intentional source, tests, documentation, DOCX, and this report remain tracked.

## Residual risks

- The <=10-minute full-flow target was met once by run 4 after the 6-step Step1X change. Run 5 took 604.844s after a Chinese audio QC retry, so three new consecutive qualifying campaigns are required before AT-001 can be marked complete.
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
- PRD verification: macOS Quick Look rendered the Chinese text correctly; DOCX a11y findings 0; 14/14 tables passed geometry audit.
