# OverseaArk E2E Verification

This suite is intentionally dependency-light: it uses only the Python standard
library so it can run on a developer laptop, CI, or DGX node without installing
browser or HTTP client packages.

## Local Mock Mode

```bash
python3 tests/e2e/run_e2e.py --mock
```

Mock mode starts an in-process OverseaArk-compatible HTTP server and verifies
the E2E contract without GPU/model access.

## Real Service Mode

```bash
OVERSEAARK_BASE_URL=http://127.0.0.1:8000 python3 tests/e2e/run_e2e.py
```

Useful environment variables:

- `OVERSEAARK_BASE_URL`: target service URL for non-mock mode.
- `OVERSEAARK_E2E_TIMEOUT`: campaign polling timeout in seconds, default `60`.
- `OVERSEAARK_E2E_EXPECT_LANGS`: comma-separated artifact language codes,
  default `zh,en,ja`.
- `OVERSEAARK_E2E_SKIP_FAULTS`: set to `1` if the target service has no fault
  injection endpoint enabled.
- `OVERSEAARK_E2E_SKIP_OFFLINE_AUDIT`: set to `1` if the target service has no
  offline audit/debug endpoint enabled.

## Expected API Contract

The suite targets this contract:

- `GET /api/v1/health` returns JSON with an ok/healthy status.
- `GET /api/v1/models` returns at least one available model.
- `POST /api/v1/campaigns` accepts `multipart/form-data` fields:
  `description`, `languages`, and `product_image`, returning a campaign id.
- `GET /api/v1/campaigns/{id}` returns state and final outputs.
- `GET /api/v1/campaigns/{id}/events` returns Server-Sent Events.
  `Last-Event-ID` resumes after the supplied sequence.
- `GET /api/v1/campaigns/{id}/export` returns a ZIP with stage outputs and
  localized artifacts.
- `POST /api/v1/campaigns/{id}/cancel` cancels an in-flight campaign.
- `POST /api/v1/campaigns/{id}/rerun/{stage}` resets the same campaign from the
  chosen stage while preserving earlier successful artifacts.
- `POST /debug/faults` can inject one transient stage failure for E2E only.
- `GET /debug/offline-audit` returns endpoint audit data for offline validation.

The approved six stages are:

1. `market_positioning`
2. `buyer_persona`
3. `multilingual_copy`
4. `visual_design`
5. `media_production`
6. `quality_packaging`

ZIP exports must contain:

- `manifest.json`
- one stage JSON for each approved stage under `stages/`
- one copy JSON for each zh/en/ja language under `copy/`
- `poster.png`
- `voice_zh.wav`, `voice_en.wav`, and `voice_ja.wav`
- `campaign_video.mp4`
- `qc_report.json`

The fault and offline-audit debug hooks are optional in real HTTP mode; tests
skip them automatically when the service returns 404.

Root test integration can invoke this lane with:

```bash
python3 tests/e2e/run_e2e.py --mock
```
