from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters import (
    AdapterError,
    MockModelHooks,
    ModelManager,
    PNG_1X1,
    _run_command,
    build_model_manager,
)
from app.main import TERMINAL_STATUSES, create_app
from app.models import CampaignCreate, CampaignStatus, StageName, StageStatus
from app.settings import Settings


def make_app(tmp_path: Path):
    return create_app(Settings(data_dir=tmp_path, adapter_mode="mock"))


@pytest.mark.asyncio
async def test_command_adapter_timeout_terminates_process_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OVERSEAARK_ADAPTER_TIMEOUT", "0.05")
    child_pid_path = tmp_path / "child.pid"
    script = tmp_path / "process_tree.py"
    script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    command = f"{sys.executable} {script} {child_pid_path}"

    with pytest.raises(AdapterError, match="process group was terminated"):
        await _run_command(command, {})

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("adapter timeout left a child process running")


@pytest.mark.asyncio
async def test_command_adapter_rejects_malformed_timeout_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "spawned"
    monkeypatch.setenv("OVERSEAARK_ADAPTER_TIMEOUT", "not-a-number")
    command = f'{sys.executable} -c "from pathlib import Path; Path(r\'{marker}\').touch()"'

    with pytest.raises(AdapterError, match="must be numeric"):
        await _run_command(command, {})

    assert not marker.exists()


async def wait_for_terminal(client: AsyncClient, campaign_id: str) -> dict:
    for _ in range(100):
        response = await client.get(f"/api/v1/campaigns/{campaign_id}")
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {status.value for status in TERMINAL_STATUSES}:
            return payload
        await asyncio.sleep(0.02)
    pytest.fail("campaign did not reach a terminal state")


@pytest.mark.asyncio
async def test_startup_resumes_campaign_left_running_by_interrupted_process(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, adapter_mode="mock")
    source_image = settings.uploads_dir / "campaigns" / "stale.png"
    source_image.parent.mkdir(parents=True, exist_ok=True)
    source_image.write_bytes(PNG_1X1)
    stale_app = create_app(settings)
    stale = stale_app.state.store.create_campaign(
        CampaignCreate(
            name="Interrupted campaign",
            description="Resume this campaign after an interrupted backend process.",
            source_market="CN",
            target_markets=["US", "JP"],
            languages=["zh", "en", "ja"],
            product_image_path=str(source_image),
        )
    )
    stale_app.state.store.set_campaign_status(
        stale.id,
        CampaignStatus.running,
        current_stage=StageName.market_positioning,
    )
    stale_app.state.store.mark_stage(
        stale.id,
        StageName.market_positioning,
        StageStatus.running,
        attempts=1,
    )

    recovered_app = create_app(settings)
    async with recovered_app.router.lifespan_context(recovered_app):
        async with AsyncClient(
            transport=ASGITransport(app=recovered_app), base_url="http://test"
        ) as client:
            recovered = await wait_for_terminal(client, stale.id)

    assert recovered["status"] == "completed"
    assert all(stage["status"] == "succeeded" for stage in recovered["stages"])
    events = recovered_app.state.store.list_events(stale.id)
    assert any(event.type == "campaign.recovered" for _, event in events)


@pytest.mark.asyncio
async def test_health_models_and_uploaded_audio_transcription(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/api/v1/health")
        models = await client.get("/api/v1/models")
        transcription = await client.post(
            "/api/v1/transcriptions",
            files={"audio": ("voice.wav", b"RIFF....WAVE", "audio/wav")},
            data={"language": "ja"},
        )

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert models.status_code == 200
    assert models.json() == {
        "llm": "ggml-org/Qwen3.6-35B-A3B-GGUF",
        "image": "stepfun-ai/Step1X-Edit-v1p2",
        "video": "nvidia/Cosmos3-Edge",
        "asr": "nvidia/nemotron-3.5-asr-streaming-0.6b",
        "tts": "nvidia/magpie_tts_multilingual_357m",
        "mode": "mock",
        "offline": True,
        "serialized": True,
    }
    assert transcription.status_code == 200
    assert transcription.json()["language"] == "ja"
    assert transcription.json()["model"] == "nvidia/nemotron-3.5-asr-streaming-0.6b"


@pytest.mark.asyncio
async def test_campaign_accepts_image_and_generates_required_artifacts(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={
                "name": "Launch",
                "description": "A compact smart travel charger for global shoppers.",
                "source_market": "CN",
                "target_markets": "US,JP",
                "languages": "zh,en,ja",
            },
        )
        assert created.status_code == 201
        campaign_id = created.json()["id"]

        completed = await wait_for_terminal(client, campaign_id)
        export = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    assert completed["status"] == "completed"
    assert [stage["name"] for stage in completed["stages"]] == [stage.value for stage in StageName]
    assert all(stage["status"] == "succeeded" for stage in completed["stages"])
    assert set(completed["artifacts"]["multilingual_copy"]["copy"]) == {"zh", "en", "ja"}
    assert all(
        {"title", "selling_points", "detail", "outreach_email", "video_script"} <= set(localized)
        for localized in completed["artifacts"]["multilingual_copy"]["copy"].values()
    )
    assert Path(completed["artifacts"]["visual_design"]["image_path"]).is_file()
    media = completed["artifacts"]["media_production"]
    assert set(media["audio"]) == {"zh", "en", "ja"}
    assert all(Path(item["audio_path"]).is_file() for item in media["audio"].values())
    assert media["audio"]["zh"]["speaker"] == "Sofia"
    assert media["audio"]["en"]["speaker"] == "Jason"
    assert media["audio"]["ja"]["speaker"] == "Aria"
    assert all(item["duration"] > 0 for item in media["audio"].values())
    assert Path(media["video"]["video_path"]).is_file()
    qc = completed["artifacts"]["quality_packaging"]["qc"]
    assert qc["passed"] is True
    assert all(item["similarity"] >= 0.75 for item in qc["audio"].values())
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert {"manifest.json", "qc_report.json", "visual_design.png", "campaign_video.mp4"} <= names
    assert {"voice_zh.wav", "voice_en.wav", "voice_ja.wav"} <= names
    assert {f"stages/{stage.value}.json" for stage in StageName} <= names
    assert {"copy/zh.json", "copy/en.json", "copy/ja.json"} <= names
    assert {"poster.png", "audio/zh.wav", "audio/en.wav", "audio/ja.wav", "video.mp4"} <= names
    assert any(name.startswith("source_image.") for name in names)
    assert manifest["offline_inference"] is True
    assert {item["id"] for item in manifest["model_manifest"]} >= {
        "nemotron-asr-streaming-0.6b",
        "magpie-tts-multilingual-357m",
    }
    assert manifest["model_calls"]


@pytest.mark.asyncio
async def test_quality_packaging_retries_low_similarity_tts_once(tmp_path: Path) -> None:
    class LowFirstTranscriptHooks(MockModelHooks):
        def __init__(self) -> None:
            self.bad_transcript_returned = False

        async def asr(self, audio_path: Path, language: str) -> dict:
            if language == "zh" and audio_path.name == "voice_zh.wav" and not self.bad_transcript_returned:
                self.bad_transcript_returned = True
                return {
                    "text": "unrelated transcript",
                    "language": language,
                    "segments": [],
                    "model": "nvidia/nemotron-asr-streaming",
                }
            return await super().asr(audio_path, language)

    app = make_app(tmp_path)
    hooks = LowFirstTranscriptHooks()
    app.state.runner.model_manager = ModelManager(hooks)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign = await wait_for_terminal(client, created.json()["id"])

    zh_audio = campaign["artifacts"]["media_production"]["audio"]["zh"]
    zh_qc = campaign["artifacts"]["quality_packaging"]["qc"]["audio"]["zh"]
    assert zh_audio["audio_path"].endswith("voice_zh_retry.wav")
    assert zh_qc["retries"] == 1
    assert zh_qc["passed"] is True


@pytest.mark.asyncio
async def test_degraded_video_quality_is_preserved_in_qc(tmp_path: Path) -> None:
    class DegradedVideoHooks(MockModelHooks):
        async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"degraded-video")
            return {
                "video_path": str(output_path),
                "prompt": prompt,
                "image_path": str(image_path),
                "model": "nvidia/Cosmos3-Edge",
                "quality": "degraded",
                "warnings": ["Cosmos fallback renderer used"],
            }

    app = make_app(tmp_path)
    app.state.runner.model_manager = ModelManager(DegradedVideoHooks())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        campaign = await wait_for_terminal(client, campaign_id)
        partial_export = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    video = campaign["artifacts"]["media_production"]["video"]
    stages = {stage["name"]: stage for stage in campaign["stages"]}
    assert campaign["status"] == "partial"
    assert video["quality"] == "degraded"
    assert stages["media_production"]["status"] == "failed"
    assert stages["quality_packaging"]["status"] == "skipped"
    assert partial_export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(partial_export.content)) as archive:
        assert {"manifest.json", "qc_report.json", "video.mp4"} <= set(archive.namelist())


@pytest.mark.asyncio
async def test_failed_stage_retries_once_then_campaign_is_partial(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    runner = app.state.runner
    calls: dict[str, int] = defaultdict(int)

    async def always_fail_visual_design(context):
        calls["visual_design"] += 1
        raise RuntimeError("image model unavailable")

    runner._stage_handlers = lambda: {  # noqa: SLF001 - test overrides stage adapter boundary.
        StageName.market_positioning: runner._market_positioning,  # noqa: SLF001
        StageName.buyer_persona: runner._buyer_persona,  # noqa: SLF001
        StageName.multilingual_copy: runner._multilingual_copy,  # noqa: SLF001
        StageName.visual_design: always_fail_visual_design,
        StageName.media_production: runner._media_production,  # noqa: SLF001
        StageName.quality_packaging: runner._quality_packaging,  # noqa: SLF001
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        campaign = await wait_for_terminal(client, campaign_id)

    assert calls["visual_design"] == 2
    assert campaign["status"] == "partial"
    assert campaign["error"] == "image model unavailable"
    by_name = {stage["name"]: stage for stage in campaign["stages"]}
    assert by_name["market_positioning"]["status"] == "succeeded"
    assert by_name["multilingual_copy"]["status"] == "succeeded"
    assert by_name["visual_design"]["status"] == "failed"
    assert by_name["visual_design"]["attempts"] == 2
    assert by_name["media_production"]["status"] == "skipped"
    assert by_name["quality_packaging"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_cancel_during_inflight_stage_remains_cancelled(tmp_path: Path) -> None:
    class SlowHooks(MockModelHooks):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def llm(self, task: str, payload: dict) -> dict:
            if task == StageName.market_positioning.value:
                self.started.set()
                await self.release.wait()
            return await super().llm(task, payload)

    app = make_app(tmp_path)
    hooks = SlowHooks()
    app.state.runner.model_manager = ModelManager(hooks)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        await asyncio.wait_for(hooks.started.wait(), timeout=1)
        cancelled = await client.post(f"/api/v1/campaigns/{campaign_id}/cancel")
        hooks.release.set()
        await asyncio.sleep(0.1)
        final = await client.get(f"/api/v1/campaigns/{campaign_id}")

    assert cancelled.json()["status"] == "cancelled"
    assert final.json()["status"] == "cancelled"
    assert all(stage["status"] == "skipped" for stage in final.json()["stages"])


@pytest.mark.asyncio
async def test_invalid_adapter_schema_fails_the_producing_stage(tmp_path: Path) -> None:
    class InvalidCopyHooks(MockModelHooks):
        async def llm(self, task: str, payload: dict) -> dict:
            if task == StageName.multilingual_copy.value:
                return {"model": "invalid-schema"}
            return await super().llm(task, payload)

    app = make_app(tmp_path)
    app.state.runner.model_manager = ModelManager(InvalidCopyHooks())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign = await wait_for_terminal(client, created.json()["id"])

    by_name = {stage["name"]: stage for stage in campaign["stages"]}
    assert campaign["status"] == "partial"
    assert by_name["multilingual_copy"]["status"] == "failed"
    assert by_name["multilingual_copy"]["attempts"] == 2
    assert by_name["visual_design"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_export_returns_conflict_until_zip_exists(tmp_path: Path) -> None:
    class SlowHooks(MockModelHooks):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def llm(self, task: str, payload: dict) -> dict:
            if task == StageName.market_positioning.value:
                self.started.set()
                await self.release.wait()
            return await super().llm(task, payload)

    app = make_app(tmp_path)
    hooks = SlowHooks()
    app.state.runner.model_manager = ModelManager(hooks)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        await asyncio.wait_for(hooks.started.wait(), timeout=1)
        response = await client.get(f"/api/v1/campaigns/{campaign_id}/export")
        hooks.release.set()
        await wait_for_terminal(client, campaign_id)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_rerun_from_stage_preserves_earlier_artifacts_and_completes(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        first = await wait_for_terminal(client, campaign_id)
        first_positioning = first["artifacts"]["market_positioning"]
        rerun = await client.post(f"/api/v1/campaigns/{campaign_id}/rerun/media_production")
        second = await wait_for_terminal(client, campaign_id)

    assert rerun.status_code == 200
    assert second["status"] == "completed"
    assert second["artifacts"]["market_positioning"] == first_positioning
    by_name = {stage["name"]: stage for stage in second["stages"]}
    assert by_name["market_positioning"]["attempts"] == 1
    assert by_name["media_production"]["attempts"] == 1
    assert by_name["quality_packaging"]["attempts"] == 1


@pytest.mark.asyncio
async def test_rejects_invalid_or_oversized_product_images(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.txt", b"not-image", "text/plain")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        oversized = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", b"0" * (20 * 1024 * 1024 + 1), "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )

    assert invalid.status_code == 415
    assert oversized.status_code == 413


def test_command_mode_requires_all_model_hooks() -> None:
    with pytest.raises(ValueError, match="requires commands for: llm, image, video, asr, tts"):
        build_model_manager("command", {})


@pytest.mark.asyncio
async def test_sse_exposes_sequence_and_resumes_from_query_or_header(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        await wait_for_terminal(client, campaign_id)
        all_events = await client.get(f"/api/v1/campaigns/{campaign_id}/events")
        resumed_by_query = await client.get(f"/api/v1/campaigns/{campaign_id}/events?last_sequence=1")
        resumed_by_header = await client.get(
            f"/api/v1/campaigns/{campaign_id}/events",
            headers={"Last-Event-ID": "1"},
        )

    assert '"sequence":1,' in all_events.text
    assert "id: 1\n" in all_events.text
    assert "id: 1\n" not in resumed_by_query.text
    assert "id: 1\n" not in resumed_by_header.text
    assert '"sequence":2,' in resumed_by_query.text
    assert '"sequence":2,' in resumed_by_header.text


@pytest.mark.asyncio
async def test_mounts_frontend_dist_with_spa_fallback(tmp_path: Path) -> None:
    dist = tmp_path / "frontend-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>OverseaArk</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    app = create_app(Settings(data_dir=tmp_path / "data", adapter_mode="mock", frontend_dist_dir=dist))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        index = await client.get("/any/client/route")
        asset = await client.get("/assets/app.js")

    assert index.status_code == 200
    assert "OverseaArk" in index.text
    assert asset.status_code == 200
    assert "console.log" in asset.text


@pytest.mark.asyncio
async def test_campaign_completion_does_not_cleanup_global_models(tmp_path: Path) -> None:
    class CleanupCountingHooks(MockModelHooks):
        def __init__(self) -> None:
            self.cleanup_calls = 0

        async def cleanup(self) -> None:
            self.cleanup_calls += 1

    app = make_app(tmp_path)
    hooks = CleanupCountingHooks()
    app.state.runner.model_manager = ModelManager(hooks)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        await wait_for_terminal(client, created.json()["id"])

    assert hooks.cleanup_calls == 0
