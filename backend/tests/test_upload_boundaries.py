from __future__ import annotations

import asyncio
import base64
import struct
import subprocess
import wave
import zlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.adapters import PNG_1X1
from app.main import TERMINAL_STATUSES, create_app
from app.settings import Settings


JPEG_1X1 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVL//2Q=="
)
WEBP_1X1 = base64.b64decode("UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA=")


def make_app(tmp_path: Path):
    return create_app(Settings(data_dir=tmp_path, adapter_mode="mock"))


def write_test_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 160)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


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
async def test_product_image_rejects_truncated_png_after_valid_signature(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    truncated_png = b"\x89PNG\r\n\x1a\n\x00"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", truncated_png, "image/png")},
            data={"description": "A compact smart travel charger for global shoppers."},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == "Upload content does not match image type"


@pytest.mark.asyncio
async def test_product_image_rejects_png_without_complete_scanline(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    empty_raster_png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(b""))
        + png_chunk(b"IEND", b"")
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns",
            files={"product_image": ("product.png", empty_raster_png, "image/png")},
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
        ("voice.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x21payload", "audio/mpeg"),
        ("voice.m4a", b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00payload", "audio/mp4"),
        ("voice.webm", b"\x1a\x45\xdf\xa3payload", "audio/webm"),
    ],
)
@pytest.mark.asyncio
async def test_audio_upload_rejects_magic_only_container(
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

    assert response.status_code == 415
    assert response.json()["detail"] == "Upload content does not match audio type"


@pytest.mark.parametrize(
    ("filename", "content_type", "encoder"),
    [
        ("voice.wav", "audio/wav", None),
        ("voice.wav", "audio/x-wav", None),
        ("voice.mp3", "audio/mpeg", ("-c:a", "libmp3lame", "-b:a", "32k")),
        ("voice.m4a", "audio/mp4", ("-c:a", "aac", "-b:a", "32k")),
        ("voice.webm", "audio/webm", ("-c:a", "libopus", "-b:a", "16k")),
    ],
)
@pytest.mark.asyncio
async def test_audio_upload_accepts_decodable_container(
    tmp_path: Path,
    filename: str,
    content_type: str,
    encoder: tuple[str, ...] | None,
) -> None:
    source = tmp_path / "source.wav"
    write_test_wav(source)
    if encoder is None:
        content = source.read_bytes()
    else:
        encoded = tmp_path / filename
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(source), *encoder, str(encoded)],
            check=True,
        )
        content = encoded.read_bytes()
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
        ("product.jpg", JPEG_1X1, "image/jpeg"),
        ("product.webp", WEBP_1X1, "image/webp"),
    ],
)
@pytest.mark.asyncio
async def test_product_image_accepts_decodable_image(
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


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("product.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01payload", "image/jpeg"),
        ("product.webp", b"RIFF\x10\x00\x00\x00WEBPVP8 payload", "image/webp"),
    ],
)
@pytest.mark.asyncio
async def test_product_image_rejects_magic_only_image(
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

    assert response.status_code == 415
    assert response.json()["detail"] == "Upload content does not match image type"


@pytest.mark.asyncio
async def test_media_decoder_checks_full_audio_and_error_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    arguments: list[str] = []

    class ErrorReportingProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"corrupt packet detected"

        def kill(self) -> None:
            return None

    async def fake_create_subprocess_exec(*args: str, **_kwargs) -> ErrorReportingProcess:
        arguments.extend(args)
        return ErrorReportingProcess()

    monkeypatch.setattr(main_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert not await main_module._media_decodes(tmp_path / "voice.mp3", "a")
    assert "-xerror" in arguments
    assert "-frames:a" not in arguments


@pytest.mark.asyncio
async def test_cancelled_media_validation_removes_partial_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    decoder_started = asyncio.Event()

    async def slow_decoder(_path: Path, _stream_type: str) -> bool:
        decoder_started.set()
        await asyncio.Event().wait()
        return True

    monkeypatch.setattr(main_module, "_media_decodes", slow_decoder)
    app = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(
            client.post(
                "/api/v1/campaigns",
                files={"product_image": ("product.png", PNG_1X1, "image/png")},
                data={"description": "A compact smart travel charger for global shoppers."},
            )
        )
        await asyncio.wait_for(decoder_started.wait(), timeout=1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

    uploaded = tmp_path / "uploads" / "campaigns"
    assert list(uploaded.glob("*")) == []


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
