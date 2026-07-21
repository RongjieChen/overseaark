from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters import MockModelHooks, ModelManager, PNG_1X1
from app.main import TERMINAL_STATUSES, create_app
from app.models import StageName
from app.settings import Settings


def make_app(tmp_path: Path):
    return create_app(Settings(data_dir=tmp_path, adapter_mode="mock"))


async def create_campaign(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/campaigns",
        files={"product_image": ("product.png", PNG_1X1, "image/png")},
        data={"description": "A compact smart travel charger for global shoppers."},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def wait_for_terminal(client: AsyncClient, campaign_id: str) -> dict[str, Any]:
    for _ in range(100):
        response = await client.get(f"/api/v1/campaigns/{campaign_id}")
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {status.value for status in TERMINAL_STATUSES}:
            return payload
        await asyncio.sleep(0.02)
    pytest.fail(f"campaign {campaign_id} did not reach a terminal state")


def parse_sse_sequences(body: str) -> list[int]:
    sequences: list[int] = []
    for block in body.strip().split("\n\n"):
        if not block:
            continue
        data_line = next(line for line in block.splitlines() if line.startswith("data: "))
        sequences.append(int(json.loads(data_line.removeprefix("data: "))["sequence"]))
    return sequences


class SlowSerializedHooks(MockModelHooks):
    def __init__(self, delay: float = 0.01) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()

    async def _track(self) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        await asyncio.sleep(self.delay)
        self.active -= 1

    async def llm(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self._track()
        return await super().llm(task, payload)

    async def image(
        self, prompt: str, source_image: Path, output_path: Path, overlay_text: str = ""
    ) -> dict[str, Any]:
        await self._track()
        return await super().image(prompt, source_image, output_path, overlay_text)

    async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict[str, Any]:
        await self._track()
        return await super().video(prompt, image_path, output_path)

    async def asr(self, audio_path: Path, language: str) -> dict[str, Any]:
        await self._track()
        return await super().asr(audio_path, language)

    async def tts(
        self,
        text: str,
        language: str,
        output_path: Path,
        speaker: str | None = None,
    ) -> dict[str, Any]:
        await self._track()
        return await super().tts(text, language, output_path, speaker)


@pytest.mark.asyncio
async def test_two_concurrent_campaigns_never_overlap_model_calls(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    hooks = SlowSerializedHooks()
    app.state.runner.model_manager = ModelManager(hooks)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_id, second_id = await asyncio.gather(create_campaign(client), create_campaign(client))
        first, second = await asyncio.gather(
            wait_for_terminal(client, first_id),
            wait_for_terminal(client, second_id),
        )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert hooks.max_active == 1


@pytest.mark.asyncio
async def test_rerun_running_campaign_returns_conflict(tmp_path: Path) -> None:
    class BlockingHooks(MockModelHooks):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def llm(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
            if task == StageName.market_positioning.value:
                self.started.set()
                await self.release.wait()
            return await super().llm(task, payload)

    app = make_app(tmp_path)
    hooks = BlockingHooks()
    app.state.runner.model_manager = ModelManager(hooks)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        campaign_id = await create_campaign(client)
        await asyncio.wait_for(hooks.started.wait(), timeout=1)
        rerun = await client.post(f"/api/v1/campaigns/{campaign_id}/rerun")
        hooks.release.set()
        final = await wait_for_terminal(client, campaign_id)

    assert rerun.status_code == 409
    assert rerun.json()["detail"] == "Campaign is already running"
    assert final["status"] == "completed"


@pytest.mark.asyncio
async def test_sse_last_sequence_resumes_after_partial_read_without_gaps(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    hooks = SlowSerializedHooks(delay=0.005)
    app.state.runner.model_manager = ModelManager(hooks)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        campaign_id = await create_campaign(client)
        await asyncio.wait_for(hooks.started.wait(), timeout=1)
        for _ in range(100):
            partial_rows = app.state.store.list_events(campaign_id)
            if len(partial_rows) >= 2:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("campaign did not publish partial events")
        partial_sequences = [event.sequence for _, event in partial_rows[:2]]
        last_sequence = partial_sequences[-1]

        await wait_for_terminal(client, campaign_id)
        full_response = await client.get(f"/api/v1/campaigns/{campaign_id}/events")
        resumed_response = await client.get(
            f"/api/v1/campaigns/{campaign_id}/events?last_sequence={last_sequence}"
        )

    full_sequences = parse_sse_sequences(full_response.text)
    resumed_sequences = parse_sse_sequences(resumed_response.text)

    assert partial_sequences == full_sequences[: len(partial_sequences)]
    assert resumed_sequences == full_sequences[len(partial_sequences) :]
    assert partial_sequences + resumed_sequences == full_sequences
    assert len(set(partial_sequences + resumed_sequences)) == len(full_sequences)


@pytest.mark.asyncio
async def test_asr_quality_failure_after_retries_returns_partial_with_failed_qc(
    tmp_path: Path,
) -> None:
    class AlwaysLowSimilarityAsrHooks(MockModelHooks):
        async def asr(self, audio_path: Path, language: str) -> dict[str, Any]:
            return {
                "text": "unrelated transcript",
                "language": language,
                "segments": [],
                "model": "nvidia/nemotron-3.5-asr-streaming-0.6b",
            }

    app = make_app(tmp_path)
    app.state.runner.model_manager = ModelManager(AlwaysLowSimilarityAsrHooks())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        campaign_id = await create_campaign(client)
        campaign = await wait_for_terminal(client, campaign_id)

    by_name = {stage["name"]: stage for stage in campaign["stages"]}
    qc = campaign["artifacts"]["quality_packaging"]["qc"]
    assert campaign["status"] == "partial"
    assert by_name["quality_packaging"]["status"] == "failed"
    assert by_name["quality_packaging"]["attempts"] == 2
    assert qc["passed"] is False
    assert all(item["passed"] is False for item in qc["audio"].values())
    assert all(item["retries"] == 1 for item in qc["audio"].values())


@pytest.mark.asyncio
async def test_degraded_cosmos_video_never_completes_campaign(tmp_path: Path) -> None:
    class DegradedCosmosHooks(MockModelHooks):
        async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict[str, Any]:
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
    app.state.runner.model_manager = ModelManager(DegradedCosmosHooks())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        campaign_id = await create_campaign(client)
        campaign = await wait_for_terminal(client, campaign_id)

    by_name = {stage["name"]: stage for stage in campaign["stages"]}
    assert campaign["status"] == "partial"
    assert campaign["status"] != "completed"
    assert by_name["media_production"]["status"] == "failed"
    assert by_name["quality_packaging"]["status"] == "skipped"
    assert campaign["artifacts"]["media_production"]["video"]["quality"] == "degraded"
