from __future__ import annotations

import asyncio
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters import MockModelHooks, ModelManager, PNG_1X1
from app.main import TERMINAL_STATUSES, create_app
from app.models import CampaignStatus, StageName
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


def assert_language_isolated(value: object, language: str) -> None:
    other_languages = {"zh", "en", "ja"} - {language}

    def visit(item: object) -> None:
        if isinstance(item, dict):
            assert not (set(item) & other_languages)
            for key, child in item.items():
                if (
                    key
                    in {
                        "language",
                        "detected_language",
                        "narration_language",
                        "lang",
                        "locale",
                    }
                    or key.endswith("_language")
                    or key.endswith("_locale")
                ) and isinstance(child, str):
                    assert child not in other_languages
                if isinstance(child, str) and (
                    key in {"artifact", "archive_path", "filename", "path"}
                    or key.endswith("_path")
                ):
                    tokens = set(
                        re.findall(
                            r"(?<![A-Za-z0-9])(zh|en|ja)(?![A-Za-z0-9])",
                            child,
                        )
                    )
                    assert not (tokens & other_languages)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)


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


@pytest.mark.asyncio
async def test_adapter_file_symlink_escape_is_rejected_before_export(tmp_path: Path) -> None:
    secret_audio = tmp_path / "outside-secret.wav"
    secret_audio.write_bytes(b"secret bytes that must never enter export.zip")

    class SymlinkEscapeAudioHooks(MockModelHooks):
        async def tts(
            self,
            text: str,
            language: str,
            output_path: Path,
            speaker: str | None = None,
        ) -> dict:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists() or output_path.is_symlink():
                output_path.unlink()
            output_path.symlink_to(secret_audio)
            output_path.with_suffix(output_path.suffix + ".txt").write_text(text, encoding="utf-8")
            return {
                "audio_path": str(output_path),
                "language": language,
                "speaker": speaker or "Jason",
                "duration": 1.0,
                "text": text,
                "model": "malicious-tts",
            }

    app = make_app(tmp_path)
    app.state.runner.model_manager = ModelManager(SymlinkEscapeAudioHooks())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        campaign = await wait_for_terminal(client, campaign_id)
        export = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    by_name = {stage["name"]: stage for stage in campaign["stages"]}
    assert campaign["status"] == "partial"
    assert by_name["media_production"]["status"] == "failed"
    assert by_name["quality_packaging"]["status"] == "skipped"
    assert "outside campaign artifact directory" in by_name["media_production"]["error"]
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        names = set(archive.namelist())
        assert "audio/zh.wav" not in names
        assert b"secret bytes that must never enter export.zip" not in export.content


@pytest.mark.asyncio
async def test_asset_endpoint_rejects_artifact_paths_outside_campaign_dir(tmp_path: Path) -> None:
    secret = tmp_path / "outside-poster.png"
    secret.write_bytes(b"secret poster")
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        campaign = await wait_for_terminal(client, campaign_id)
        artifacts = campaign["artifacts"]
        artifacts[StageName.visual_design.value]["image_path"] = str(secret)
        app.state.store.set_campaign_status(
            campaign_id,
            CampaignStatus.completed,
            artifacts=artifacts,
        )
        asset = await client.get(f"/api/v1/campaigns/{campaign_id}/assets/poster")
        export = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    assert asset.status_code == 404
    assert b"secret poster" not in export.content


@pytest.mark.asyncio
async def test_single_language_export_filters_every_nested_language_and_mismatched_video(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign_id = created.json()["id"]
        campaign = await wait_for_terminal(client, campaign_id)
        artifacts = campaign["artifacts"]
        artifacts[StageName.media_production.value]["video"]["narration_language"] = "en"
        app.state.store.set_campaign_status(
            campaign_id,
            CampaignStatus.completed,
            artifacts=artifacts,
        )

        manifest_path = Path(
            artifacts[StageName.quality_packaging.value]["manifest_path"]
        )
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_manifest["artifacts"] = artifacts
        existing_manifest["deeply_nested"] = {
            "items": [
                {"language": "zh", "value": "keep"},
                {"language": "en", "value": "remove"},
                {"language": "ja", "value": "remove"},
                {"path": "/campaign/voice_zh.wav", "value": "keep"},
                {"path": "/campaign/voice_en.wav", "value": "remove"},
            ],
            "by_language": {
                "zh": {"passed": True},
                "en": {"passed": False},
                "ja": {"passed": False},
            },
            "supported_locales": ["zh", "en", "ja"],
            "locale_items": [
                {"locale": "zh", "value": "keep"},
                {"locale": "en", "value": "remove"},
                {"locale": "ja", "value": "remove"},
            ],
        }
        existing_manifest["model_calls"].extend(
            [
                {"artifact": "artifacts.media_production.audio.zh", "model": "tts-zh"},
                {"artifact": "artifacts.media_production.audio.en", "model": "tts-en"},
                {"artifact": "artifacts.media_production.audio.ja", "model": "tts-ja"},
                {"artifact": "artifacts.media_production.video", "model": "video-en"},
            ]
        )
        manifest_path.write_text(
            json.dumps(existing_manifest, ensure_ascii=False),
            encoding="utf-8",
        )

        chinese_export = await client.get(
            f"/api/v1/campaigns/{campaign_id}/export?language=zh"
        )
        english_export = await client.get(
            f"/api/v1/campaigns/{campaign_id}/export?language=en"
        )
        full_export = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    assert chinese_export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(chinese_export.content)) as archive:
        chinese_names = set(archive.namelist())
        chinese_manifest = json.loads(archive.read("manifest.json"))
        chinese_qc = json.loads(archive.read("qc_report.json"))
        chinese_media_stage = json.loads(archive.read("stages/media_production.json"))
    assert {"zh/", "zh/copy.json", "zh/audio.wav", "audio/zh.wav", "voice_zh.wav"} <= chinese_names
    assert not any(name.endswith(".mp4") for name in chinese_names)
    assert not {
        "en/",
        "ja/",
        "audio/en.wav",
        "audio/ja.wav",
        "voice_en.wav",
        "voice_ja.wav",
    } & chinese_names
    assert set(chinese_manifest["artifacts"]["media_production"]["audio"]) == {"zh"}
    assert "video" not in chinese_manifest["artifacts"]["media_production"]
    assert set(chinese_manifest["qc"]["audio"]) == {"zh"}
    assert set(chinese_qc["audio"]) == {"zh"}
    assert "video" not in chinese_media_stage
    assert chinese_manifest["language_assets"]["video"] == {
        "included": False,
        "scope": "language",
        "reason": "no_verified_matching_narration",
    }
    assert [item["value"] for item in chinese_manifest["deeply_nested"]["items"]] == [
        "keep",
        "keep",
    ]
    assert set(chinese_manifest["deeply_nested"]["by_language"]) == {"zh"}
    assert chinese_manifest["deeply_nested"]["supported_locales"] == ["zh"]
    assert chinese_manifest["deeply_nested"]["locale_items"] == [
        {"locale": "zh", "value": "keep"}
    ]
    assert not any(
        call.get("artifact", "").endswith((".audio.en", ".audio.ja", ".video"))
        for call in chinese_manifest["model_calls"]
    )
    assert_language_isolated(chinese_manifest, "zh")
    assert_language_isolated(chinese_qc, "zh")

    assert english_export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(english_export.content)) as archive:
        english_names = set(archive.namelist())
        english_manifest = json.loads(archive.read("manifest.json"))
    assert {
        "shared/video.mp4",
        "campaign_video.mp4",
        "video.mp4",
        "en/video.mp4",
    } <= english_names
    assert english_manifest["language_assets"]["video"]["narration_language"] == "en"
    assert_language_isolated(english_manifest, "en")

    assert full_export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(full_export.content)) as archive:
        full_names = set(archive.namelist())
        full_manifest = json.loads(archive.read("manifest.json"))
    assert "shared/video.mp4" in full_names
    assert full_manifest["shared_assets"]["video"] == {
        "included": True,
        "scope": "shared",
        "archive_path": "shared/video.mp4",
        "narration_language": "en",
        "single_language_exports_require_matching_narration": True,
    }


@pytest.mark.asyncio
async def test_full_export_only_has_requested_language_and_rebuilds_missing_legacy_zip(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", PNG_1X1, "image/png")},
            data={
                "description": "A compact smart travel charger for global shoppers.",
                "languages": "en",
            },
        )
        campaign_id = created.json()["id"]
        campaign = await wait_for_terminal(client, campaign_id)
        legacy_export_path = Path(
            campaign["artifacts"][StageName.quality_packaging.value]["zip_path"]
        )
        assert legacy_export_path.is_file()
        legacy_export_path.unlink()

        rebuilt = await client.get(f"/api/v1/campaigns/{campaign_id}/export")

    assert rebuilt.status_code == 200
    assert legacy_export_path.is_file()
    with zipfile.ZipFile(io.BytesIO(rebuilt.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert "en/" in names
    assert not {"zh/", "ja/", "copy/zh.json", "copy/ja.json"} & names
    assert not {"audio/zh.wav", "audio/ja.wav", "voice_zh.wav", "voice_ja.wav"} & names
    assert manifest["languages"] == ["en"]
