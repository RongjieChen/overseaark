from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters import PNG_1X1
from app.main import TERMINAL_STATUSES, create_app
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


@pytest.mark.asyncio
async def test_product_image_rejects_forged_png_content_type(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", b"not really a png", "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == "Upload content does not match image type"


@pytest.mark.asyncio
async def test_product_image_rejects_empty_supported_content_type(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", b"", "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload cannot be empty"


@pytest.mark.asyncio
async def test_audio_upload_rejects_forged_wav_content_type(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/transcriptions",
            files={"audio": ("voice.wav", b"random bytes pretending to be wav", "audio/wav")},
            data={"language": "auto"},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == "Upload content does not match audio type"


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("voice.wav", b"RIFF\x24\x00\x00\x00WAVEfmt payload", "audio/wav"),
        ("voice.wav", b"RIFF\x24\x00\x00\x00WAVEfmt payload", "audio/x-wav"),
        ("voice.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x21payload", "audio/mpeg"),
        ("voice.m4a", b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00payload", "audio/mp4"),
        ("voice.webm", b"\x1a\x45\xdf\xa3payload", "audio/webm"),
    ],
)
@pytest.mark.asyncio
async def test_audio_upload_accepts_matching_audio_magic(
    tmp_path: Path,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/transcriptions",
            files={"audio": (filename, content, content_type)},
            data={"language": "auto"},
        )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("product.png", PNG_1X1, "image/png"),
        ("product.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01payload", "image/jpeg"),
        ("product.webp", b"RIFF\x10\x00\x00\x00WEBPVP8 payload", "image/webp"),
    ],
)
@pytest.mark.asyncio
async def test_product_image_accepts_matching_image_magic(
    tmp_path: Path,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns",
            files={"product_image": (filename, content, content_type)},
            data={"description": "A compact smart travel charger for global shoppers."},
        )
        campaign = await wait_for_terminal(client, response.json()["id"])

    assert response.status_code == 201
    assert campaign["status"] == "completed"


@pytest.mark.asyncio
async def test_product_image_keeps_streaming_size_limit(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    oversized_png = b"\x89PNG\r\n\x1a\n" + b"0" * (20 * 1024 * 1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", oversized_png, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )

    assert response.status_code == 413
