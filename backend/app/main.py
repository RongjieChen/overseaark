from __future__ import annotations

import asyncio
import json
import struct
import uuid
import zipfile
import zlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .adapters import (
    IMAGE_MODEL,
    LLM_MODEL,
    MAGPIE_TTS_MODEL,
    NEMOTRON_ASR_MODEL,
    VIDEO_MODEL,
    build_model_manager,
)
from .models import (
    DEFAULT_LANGUAGES,
    STAGE_ORDER,
    CampaignCreate,
    CampaignDetail,
    CampaignStatus,
    HealthResponse,
    ModelInfo,
    StageName,
    StageStatus,
    TranscriptionResponse,
)
from .pipeline import CampaignRunner
from .settings import Settings, get_settings
from .store import Store


TERMINAL_STATUSES = {
    CampaignStatus.completed,
    CampaignStatus.partial,
    CampaignStatus.failed,
    CampaignStatus.cancelled,
}
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
IMAGE_MAGIC_PREFIXES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
ALLOWED_AUDIO_TYPES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/webm": ".webm",
}
MP3_FRAME_SYNC_SECOND_BYTES = frozenset({0xE2, 0xE3, 0xEA, 0xEB, 0xF2, 0xF3, 0xFA, 0xFB})
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app_settings.data_dir.mkdir(parents=True, exist_ok=True)
    app_settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    app_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    store = Store(app_settings.db_path)
    model_manager = build_model_manager(
        app_settings.adapter_mode,
        {
            "llm": app_settings.llm_command,
            "llm_control": app_settings.llm_control_command,
            "image": app_settings.image_command,
            "video": app_settings.video_command,
            "asr": app_settings.asr_command,
            "tts": app_settings.tts_command,
        },
    )
    runner = CampaignRunner(store, model_manager, app_settings.artifacts_dir)
    tasks: set[asyncio.Task[None]] = set()
    campaign_tasks: dict[str, asyncio.Task[None]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for summary in store.list_campaigns():
            if summary.status not in {CampaignStatus.queued, CampaignStatus.running}:
                continue
            campaign = store.get_campaign(summary.id)
            first_incomplete = next(
                (stage.name for stage in campaign.stages if stage.status != StageStatus.succeeded),
                None,
            )
            if first_incomplete is None:
                store.set_campaign_status(
                    campaign.id,
                    CampaignStatus.completed,
                    artifacts=campaign.artifacts,
                )
                store.add_event(
                    campaign.id,
                    "campaign.recovered",
                    "Recovered completed campaign state after backend restart",
                )
                continue
            if first_incomplete not in STAGE_ORDER:
                continue
            store.reset_campaign_for_rerun(
                campaign.id,
                first_incomplete,
                event_type="campaign.recovered",
                event_message=(
                    "Recovered interrupted campaign after backend restart from "
                    f"{first_incomplete.value}"
                ),
            )
            schedule(campaign.id, from_stage=first_incomplete)
        yield
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await model_manager.cleanup()

    app = FastAPI(title="OverseaArk Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.store = store
    app.state.runner = runner
    app.state.tasks = tasks
    app.state.campaign_tasks = campaign_tasks

    def schedule(campaign_id: str, from_stage: StageName = StageName.market_positioning) -> None:
        task = asyncio.create_task(runner.run(campaign_id, from_stage=from_stage))
        tasks.add(task)
        campaign_tasks[campaign_id] = task

        def cleanup(done: asyncio.Task[None]) -> None:
            tasks.discard(done)
            if campaign_tasks.get(campaign_id) is done:
                campaign_tasks.pop(campaign_id, None)

        task.add_done_callback(cleanup)

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", storage_path=str(app_settings.data_dir))

    @app.get("/health", response_model=HealthResponse)
    async def legacy_health() -> HealthResponse:
        return await health()

    @app.get("/api/v1/models", response_model=ModelInfo)
    async def models() -> ModelInfo:
        return ModelInfo(
            llm=LLM_MODEL,
            image=IMAGE_MODEL,
            video=VIDEO_MODEL,
            asr=NEMOTRON_ASR_MODEL,
            tts=MAGPIE_TTS_MODEL,
            mode=app_settings.adapter_mode,
            offline=app_settings.offline_only,
        )

    @app.post("/api/v1/transcriptions", response_model=TranscriptionResponse)
    async def transcriptions(
        audio: UploadFile = File(...),
        language: str = Form("auto"),
    ) -> TranscriptionResponse:
        audio_path = await _save_upload(
            audio,
            app_settings.uploads_dir / "transcriptions",
            ALLOWED_AUDIO_TYPES,
            max_bytes=MAX_IMAGE_BYTES,
            validate_audio_magic=True,
        )
        result = await model_manager.asr(audio_path, language)
        return TranscriptionResponse(**result)

    @app.post(
        "/api/v1/campaigns",
        response_model=CampaignDetail,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_campaign(
        product_image: UploadFile = File(...),
        description: str = Form(..., min_length=5, max_length=2000),
        audio_transcription: str = Form("", max_length=4000),
        name: str = Form("Untitled campaign", min_length=1, max_length=160),
        source_market: str = Form("CN"),
        target_markets: str = Form("US,JP"),
        languages: str = Form(",".join(DEFAULT_LANGUAGES)),
    ) -> CampaignDetail:
        image_path = await _save_upload(
            product_image,
            app_settings.uploads_dir / "campaigns",
            ALLOWED_IMAGE_TYPES,
            max_bytes=MAX_IMAGE_BYTES,
            validate_image_magic=True,
        )
        payload = CampaignCreate(
            name=name,
            description=description,
            audio_transcription=audio_transcription,
            source_market=source_market,
            target_markets=_parse_csv(target_markets),
            languages=_normalize_languages(languages),
            product_image_path=str(image_path),
        )
        campaign = store.create_campaign(payload)
        schedule(campaign.id)
        return campaign

    @app.get("/api/v1/campaigns", response_model=list[CampaignDetail])
    async def list_campaigns() -> list[CampaignDetail]:
        return [store.get_campaign(campaign.id) for campaign in store.list_campaigns()]

    @app.get("/api/v1/campaigns/{campaign_id}", response_model=CampaignDetail)
    async def get_campaign(campaign_id: str) -> CampaignDetail:
        return _get_campaign_or_404(store, campaign_id)

    @app.post("/api/v1/campaigns/{campaign_id}/rerun/{stage}", response_model=CampaignDetail)
    async def rerun_campaign(campaign_id: str, stage: StageName) -> CampaignDetail:
        campaign = _get_campaign_or_404(store, campaign_id)
        if campaign.status in {CampaignStatus.queued, CampaignStatus.running}:
            raise HTTPException(status_code=409, detail="Campaign is already running")
        store.reset_campaign_for_rerun(campaign_id, stage)
        schedule(campaign_id, from_stage=stage)
        return store.get_campaign(campaign_id)

    @app.post("/api/v1/campaigns/{campaign_id}/rerun", response_model=CampaignDetail)
    async def rerun_full_campaign(campaign_id: str) -> CampaignDetail:
        return await rerun_campaign(campaign_id, StageName.market_positioning)

    @app.post("/api/v1/campaigns/{campaign_id}/cancel", response_model=CampaignDetail)
    async def cancel_campaign(campaign_id: str) -> CampaignDetail:
        campaign = _get_campaign_or_404(store, campaign_id)
        if campaign.status in TERMINAL_STATUSES:
            return campaign
        store.request_cancel(campaign_id)
        task = campaign_tasks.get(campaign_id)
        if task is not None and not task.done():
            task.cancel()
        return store.get_campaign(campaign_id)

    @app.get("/api/v1/campaigns/{campaign_id}/export")
    async def export_campaign(campaign_id: str) -> Response:
        campaign = _get_campaign_or_404(store, campaign_id)
        package = campaign.artifacts.get(StageName.quality_packaging.value, {})
        zip_path = package.get("zip_path")
        if zip_path and Path(zip_path).is_file():
            return FileResponse(zip_path, media_type="application/zip", filename="overseaark-export.zip")
        if campaign.status == CampaignStatus.partial and campaign.artifacts:
            partial_zip = _build_partial_export(campaign, app_settings.artifacts_dir)
            return FileResponse(
                partial_zip,
                media_type="application/zip",
                filename="overseaark-partial-export.zip",
            )
        raise HTTPException(status_code=409, detail="Campaign ZIP is not available yet")

    @app.get("/api/v1/campaigns/{campaign_id}/events")
    async def campaign_events(
        campaign_id: str,
        request: Request,
        last_sequence: int = 0,
    ) -> StreamingResponse:
        _get_campaign_or_404(store, campaign_id)
        header_sequence = _parse_last_event_id(request.headers.get("last-event-id"))
        start_sequence = max(last_sequence, header_sequence)

        async def stream() -> AsyncIterator[str]:
            last_id = start_sequence
            while True:
                rows = store.list_events(campaign_id, after_id=last_id)
                for event_id, event in rows:
                    last_id = event.sequence
                    yield (
                        f"id: {event.sequence}\n"
                        "event: campaign\n"
                        f"data: {event.model_dump_json()}\n\n"
                    )
                campaign = store.get_campaign(campaign_id)
                if campaign.status in TERMINAL_STATUSES and not rows:
                    break
                if await request.is_disconnected():
                    break
                await asyncio.sleep(0.1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    _mount_frontend(app, app_settings.frontend_dist_dir)

    return app


async def _save_upload(
    upload: UploadFile,
    target_dir: Path,
    allowed_types: dict[str, str],
    max_bytes: int,
    validate_image_magic: bool = False,
    validate_audio_magic: bool = False,
) -> Path:
    content_type = upload.content_type or ""
    suffix = allowed_types.get(content_type)
    if suffix is None:
        raise HTTPException(status_code=415, detail="Unsupported upload content type")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{uuid.uuid4()}{suffix}"
    size = 0
    head = b""
    accepted = False
    try:
        with path.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail="Upload exceeds 20MB limit")
                if len(head) < 16:
                    head = (head + chunk)[:16]
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Upload cannot be empty")
        if validate_image_magic and not _matches_image_magic(content_type, head):
            raise HTTPException(status_code=415, detail="Upload content does not match image type")
        if validate_image_magic and content_type == "image/png" and not _is_valid_png(path):
            raise HTTPException(status_code=415, detail="Upload content does not match image type")
        if validate_image_magic and not await _media_decodes(path, "v"):
            raise HTTPException(status_code=415, detail="Upload content does not match image type")
        if validate_audio_magic and not _matches_audio_magic(content_type, head):
            raise HTTPException(status_code=415, detail="Upload content does not match audio type")
        if validate_audio_magic and not await _media_decodes(path, "a"):
            raise HTTPException(status_code=415, detail="Upload content does not match audio type")
        accepted = True
        return path
    finally:
        if not accepted:
            path.unlink(missing_ok=True)


def _matches_image_magic(content_type: str, head: bytes) -> bool:
    if content_type == "image/webp":
        return len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    return any(head.startswith(prefix) for prefix in IMAGE_MAGIC_PREFIXES.get(content_type, ()))


def _is_valid_png(path: Path) -> bool:
    try:
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return False

        offset = 8
        seen_ihdr = False
        seen_idat = False
        seen_iend = False
        idat = bytearray()
        width = 0
        height = 0
        bit_depth = 0
        color_type = 0
        interlace = 0
        while offset < len(data):
            if offset + 12 > len(data):
                return False
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            chunk_end = offset + 12 + length
            if chunk_end > len(data):
                return False
            chunk_data = data[offset + 8 : offset + 8 + length]
            expected_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
            actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
            if actual_crc != expected_crc:
                return False

            if chunk_type == b"IHDR":
                if seen_ihdr or offset != 8 or length != 13:
                    return False
                width, height = struct.unpack(">II", chunk_data[:8])
                if width < 1 or height < 1 or width > 16_384 or height > 16_384:
                    return False
                if width * height > 50_000_000:
                    return False
                bit_depth, color_type, compression, filter_method, interlace = chunk_data[8:]
                valid_depths = {
                    0: {1, 2, 4, 8, 16},
                    2: {8, 16},
                    3: {1, 2, 4, 8},
                    4: {8, 16},
                    6: {8, 16},
                }
                if bit_depth not in valid_depths.get(color_type, set()):
                    return False
                if compression != 0 or filter_method != 0 or interlace not in {0, 1}:
                    return False
                seen_ihdr = True
            elif chunk_type == b"IDAT":
                if not seen_ihdr or seen_iend:
                    return False
                seen_idat = True
                idat.extend(chunk_data)
            elif chunk_type == b"IEND":
                if length != 0 or not seen_idat:
                    return False
                seen_iend = True
                offset = chunk_end
                break
            offset = chunk_end

        if not (seen_ihdr and seen_idat and seen_iend) or offset != len(data):
            return False
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        bits_per_pixel = channels * bit_depth
        if interlace == 0:
            passes = [(width, height)]
        else:
            adam7 = (
                (0, 0, 8, 8),
                (4, 0, 8, 8),
                (0, 4, 4, 8),
                (2, 0, 4, 4),
                (0, 2, 2, 4),
                (1, 0, 2, 2),
                (0, 1, 1, 2),
            )
            passes = [
                (
                    (width - x_start + x_step - 1) // x_step if width > x_start else 0,
                    (height - y_start + y_step - 1) // y_step if height > y_start else 0,
                )
                for x_start, y_start, x_step, y_step in adam7
            ]
        expected_size = sum(
            pass_height * (1 + (pass_width * bits_per_pixel + 7) // 8)
            for pass_width, pass_height in passes
            if pass_width and pass_height
        )
        decompressor = zlib.decompressobj()
        compressed = bytes(idat)
        decompressed_size = 0
        while compressed:
            output = decompressor.decompress(compressed, 1024 * 1024)
            decompressed_size += len(output)
            if decompressed_size > 256 * 1024 * 1024:
                return False
            remaining = decompressor.unconsumed_tail
            if not output and len(remaining) == len(compressed):
                return False
            compressed = remaining
        return (
            decompressor.eof
            and not decompressor.unused_data
            and decompressed_size == expected_size
        )
    except (OSError, struct.error, zlib.error):
        return False


async def _media_decodes(path: Path, stream_type: str) -> bool:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-xerror",
        "-nostdin",
        "-threads",
        "1",
        "-i",
        str(path),
        "-map",
        f"0:{stream_type}:0",
    ]
    if stream_type == "v":
        command.extend(("-frames:v", "1"))
    command.extend(("-f", "null", "-"))
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return False

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return False
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise
    return process.returncode == 0 and not stderr.strip()


def _matches_audio_magic(content_type: str, head: bytes) -> bool:
    if content_type in {"audio/wav", "audio/x-wav"}:
        return len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WAVE"
    if content_type == "audio/mpeg":
        return head.startswith(b"ID3") or (
            len(head) >= 2 and head[0] == 0xFF and head[1] in MP3_FRAME_SYNC_SECOND_BYTES
        )
    if content_type == "audio/mp4":
        return len(head) >= 12 and head[4:8] == b"ftyp"
    if content_type == "audio/webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    return False


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_languages(value: str) -> list[str]:
    requested = _parse_csv(value) or list(DEFAULT_LANGUAGES)
    unsupported = [language for language in requested if language not in DEFAULT_LANGUAGES]
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported languages: {', '.join(unsupported)}; supported: zh,en,ja",
        )
    return list(dict.fromkeys(requested))


def _get_campaign_or_404(store: Store, campaign_id: str) -> CampaignDetail:
    try:
        return store.get_campaign(campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Campaign not found") from exc


def _parse_last_event_id(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _mount_frontend(app: FastAPI, configured_dist_dir: Path | None = None) -> None:
    project_root = Path(__file__).resolve().parents[2]
    dist_dir = configured_dist_dir or project_root / "runtime" / "frontend-dist"
    if not dist_dir.is_dir():
        return
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_spa(full_path: str) -> FileResponse:
        requested = (dist_dir / full_path).resolve()
        if requested.is_file() and dist_dir.resolve() in requested.parents:
            return FileResponse(requested)
        if Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Frontend asset not found")
        index = dist_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend not found")


def _build_partial_export(campaign: CampaignDetail, artifacts_dir: Path) -> Path:
    package_dir = artifacts_dir / campaign.id
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "partial-export.zip"
    qc_report = {
        "passed": False,
        "quality": "partial",
        "campaign_status": campaign.status.value,
        "error": campaign.error,
        "offline_inference": True,
    }
    manifest = {
        "campaign_id": campaign.id,
        "name": campaign.name,
        "status": campaign.status.value,
        "error": campaign.error,
        "languages": campaign.languages,
        "artifacts": campaign.artifacts,
        "stages": [stage.model_dump(mode="json") for stage in campaign.stages],
        "quality": "partial",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("qc_report.json", json.dumps(qc_report, ensure_ascii=False, indent=2))
        source = Path(campaign.product_image_path)
        if source.is_file():
            archive.write(source, f"source_image{source.suffix}")
        for stage_name, output in campaign.artifacts.items():
            archive.writestr(f"stages/{stage_name}.json", json.dumps(output, ensure_ascii=False, indent=2))
        copy = campaign.artifacts.get(StageName.multilingual_copy.value, {}).get("copy", {})
        for language, localized in copy.items():
            archive.writestr(
                f"copy/{language}.json", json.dumps(localized, ensure_ascii=False, indent=2)
            )
        visual_path = campaign.artifacts.get(StageName.visual_design.value, {}).get("image_path")
        if visual_path and Path(visual_path).is_file():
            archive.write(visual_path, "poster.png")
        media = campaign.artifacts.get(StageName.media_production.value, {})
        for language, item in media.get("audio", {}).items():
            audio_path = item.get("audio_path")
            if audio_path and Path(audio_path).is_file():
                archive.write(audio_path, f"audio/{language}.wav")
        video_path = media.get("video", {}).get("video_path")
        if video_path and Path(video_path).is_file():
            archive.write(video_path, "video.mp4")
    return path


app = create_app()
