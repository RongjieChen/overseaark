from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path, PurePosixPath

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters import MockModelHooks, ModelManager, PNG_1X1
from app.main import TERMINAL_STATUSES, create_app
from app.models import StageName
from app.settings import Settings


def make_app(tmp_path: Path):
    return create_app(Settings(data_dir=tmp_path, adapter_mode="mock"))


async def wait_for_terminal(client: AsyncClient, campaign_id: str) -> dict:
    for _ in range(100):
        response = await client.get(f"/api/v1/campaigns/{campaign_id}")
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {status.value for status in TERMINAL_STATUSES}:
            return payload
        await asyncio.sleep(0.02)
    pytest.fail("campaign did not reach a terminal state")


def assert_safe_zip(response_content: bytes, required_names: set[str]) -> tuple[dict, dict, set[str]]:
    with zipfile.ZipFile(io.BytesIO(response_content)) as archive:
        names = set(archive.namelist())
        for name in names:
            path = PurePosixPath(name)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert "" not in path.parts
            assert all(part not in {".", ".."} for part in path.parts)
        assert required_names <= names
        manifest = json.loads(archive.read("manifest.json"))
        qc_report = json.loads(archive.read("qc_report.json"))
    assert isinstance(manifest, dict)
    assert isinstance(qc_report, dict)
    return manifest, qc_report, names


@pytest.mark.asyncio
async def test_completed_export_zip_members_are_safe_and_manifested(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        campaign = await wait_for_terminal(client, campaign_id)
        export = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    assert campaign["status"] == "completed"
    assert export.status_code == 200
    manifest, qc_report, names = assert_safe_zip(
        export.content,
        {
            "manifest.json",
            "qc_report.json",
            "campaign_video.mp4",
            "video.mp4",
            "poster.png",
            "audio/zh.wav",
            "audio/en.wav",
            "audio/ja.wav",
        },
    )
    assert {f"stages/{stage.value}.json" for stage in StageName} <= names
    assert {"copy/zh.json", "copy/en.json", "copy/ja.json"} <= names
    assert any(name.startswith("source_image.") for name in names)
    assert manifest["campaign_id"] == campaign_id
    assert manifest["offline_inference"] is True
    assert qc_report["passed"] is True


@pytest.mark.asyncio
async def test_partial_export_zip_members_are_safe_and_manifested(tmp_path: Path) -> None:
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
        export = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    assert campaign["status"] == "partial"
    assert export.status_code == 200
    manifest, qc_report, names = assert_safe_zip(
        export.content,
        {
            "manifest.json",
            "qc_report.json",
            "video.mp4",
            "poster.png",
            "audio/zh.wav",
            "audio/en.wav",
            "audio/ja.wav",
        },
    )
    assert {"stages/market_positioning.json", "stages/media_production.json"} <= names
    assert any(name.startswith("source_image.") for name in names)
    assert manifest["campaign_id"] == campaign_id
    assert manifest["quality"] == "partial"
    assert qc_report["passed"] is False
