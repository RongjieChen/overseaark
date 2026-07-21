from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import shutil
import shlex
import time
import wave
from abc import ABC
from pathlib import Path
from typing import Any


LLM_MODEL = "stepfun-ai/Step3-VL-10B-FP8"
IMAGE_MODEL = "stepfun-ai/Step1X-Edit-v1p2"
VIDEO_MODEL = "nvidia/Cosmos3-Edge"
NEMOTRON_ASR_MODEL = "nvidia/nemotron-3.5-asr-streaming-0.6b"
MAGPIE_TTS_MODEL = "nvidia/magpie_tts_multilingual_357m"
DEFAULT_TTS_SPEAKERS = {"zh": "Sofia", "en": "Jason", "ja": "Aria"}

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class AdapterError(RuntimeError):
    pass


class ModelHooks(ABC):
    mode = "mock"

    async def llm(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def image(
        self, prompt: str, source_image: Path, output_path: Path, overlay_text: str = ""
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict[str, Any]:
        raise NotImplementedError

    async def asr(self, audio_path: Path, language: str) -> dict[str, Any]:
        raise NotImplementedError

    async def tts(
        self,
        text: str,
        language: str,
        output_path: Path,
        speaker: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def cleanup(self) -> None:
        return None


class MockModelHooks(ModelHooks):
    mode = "mock"

    async def llm(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0)
        description = payload.get("description", "")
        if task == "market_positioning":
            return {
                "positioning": "Premium cross-border product for practical daily use",
                "differentiators": ["localized trust", "clear value", "fast launch"],
                "market_hypotheses": ["Validate demand with localized marketplace listings before paid scale"],
                "source_market": payload.get("source_market"),
                "target_markets": payload.get("target_markets", []),
                "model": LLM_MODEL,
            }
        if task == "buyer_persona":
            return {
                "personas": [
                    {
                        "name": "Value-focused explorer",
                        "pain_points": ["unclear product proof", "high switching risk"],
                        "purchase_motivations": ["practical value", "localized trust"],
                        "channel_recommendations": ["marketplace listing", "creator demo", "email outreach"],
                        "needs": ["proof", "simple onboarding", "localized copy"],
                    }
                ],
                "model": LLM_MODEL,
            }
        if task == "multilingual_copy":
            languages = payload.get("languages", ["zh", "en", "ja"])
            return {
                "copy": {
                    language: {
                        "headline": f"{language.upper()} launch headline",
                        "title": f"{language.upper()} launch headline",
                        "selling_points": ["Localized trust", "Practical value", "Fast launch"],
                        "detail": f"{description[:120]} ({language})",
                        "body": f"{description[:120]} ({language})",
                        "outreach_email": f"A localized partner introduction for {description[:80]} ({language})",
                        "video_script": f"{description[:120]} ({language})",
                        "cta": {"zh": "立即了解", "en": "Learn more", "ja": "詳しく見る"}.get(
                            language, "Learn more"
                        ),
                    }
                    for language in languages
                },
                "model": LLM_MODEL,
            }
        if task == "quality_packaging":
            return {
                "qc": {
                    "passed": True,
                    "checks": ["languages", "image", "audio", "video", "archive"],
                },
                "model": LLM_MODEL,
            }
        return {"text": f"Mock {task}", "model": LLM_MODEL}

    async def image(
        self, prompt: str, source_image: Path, output_path: Path, overlay_text: str = ""
    ) -> dict[str, Any]:
        await asyncio.sleep(0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(PNG_1X1)
        return {
            "image_path": str(output_path),
            "prompt": prompt,
            "source_image_path": str(source_image),
            "overlay_text": overlay_text,
            "model": IMAGE_MODEL,
        }

    async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict[str, Any]:
        await asyncio.sleep(0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(_minimal_mp4())
        return {
            "video_path": str(output_path),
            "prompt": prompt,
            "image_path": str(image_path),
            "model": VIDEO_MODEL,
            "quality": "standard",
            "warnings": [],
        }

    async def asr(self, audio_path: Path, language: str) -> dict[str, Any]:
        await asyncio.sleep(0)
        detected_language = "en" if language == "auto" else language
        sidecar = audio_path.with_suffix(audio_path.suffix + ".txt")
        text = sidecar.read_text(encoding="utf-8") if sidecar.is_file() else f"Mock transcript for {audio_path.stem}"
        return {
            "text": text,
            "language": detected_language,
            "segments": [{"start": 0.0, "end": 1.0, "text": text}],
            "model": NEMOTRON_ASR_MODEL,
        }

    async def tts(
        self,
        text: str,
        language: str,
        output_path: Path,
        speaker: str | None = None,
    ) -> dict[str, Any]:
        await asyncio.sleep(0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = _write_silent_wav(output_path)
        output_path.with_suffix(output_path.suffix + ".txt").write_text(text, encoding="utf-8")
        selected_speaker = speaker or DEFAULT_TTS_SPEAKERS.get(language, "Jason")
        return {
            "audio_path": str(output_path),
            "language": language,
            "speaker": selected_speaker,
            "duration": duration,
            "text": text,
            "model": MAGPIE_TTS_MODEL,
        }


class CommandModelHooks(ModelHooks):
    mode = "command"

    def __init__(self, commands: dict[str, str]):
        self.commands = commands

    async def llm(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await _run_command(self.commands["llm"], {"task": task, **payload})

    async def image(
        self, prompt: str, source_image: Path, output_path: Path, overlay_text: str = ""
    ) -> dict[str, Any]:
        result = await _run_command(
            self.commands["image"],
            {
                "prompt": prompt,
                "source_image": str(source_image),
                "output_path": str(output_path),
                "overlay_text": overlay_text,
            },
        )
        result.setdefault("image_path", str(output_path))
        return result

    async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict[str, Any]:
        try:
            result = await _run_command(
                self.commands["video"],
                {"prompt": prompt, "image_path": str(image_path), "output_path": str(output_path)},
            )
        except AdapterError as exc:
            if os.environ.get("OVERSEAARK_ALLOW_DEGRADED_VIDEO", "1") != "1":
                raise
            result = await _ffmpeg_degraded_video(image_path, output_path, str(exc))
        result.setdefault("video_path", str(output_path))
        return result

    async def asr(self, audio_path: Path, language: str) -> dict[str, Any]:
        result = await _run_command(
            self.commands["asr"],
            {"audio_path": str(audio_path), "language": language},
        )
        for key in ("text", "language", "segments"):
            if key not in result:
                raise AdapterError(f"ASR command output missing {key!r}")
        result.setdefault("model", NEMOTRON_ASR_MODEL)
        return result

    async def tts(
        self,
        text: str,
        language: str,
        output_path: Path,
        speaker: str | None = None,
    ) -> dict[str, Any]:
        selected_speaker = speaker or DEFAULT_TTS_SPEAKERS.get(language, "Jason")
        result = await _run_command(
            self.commands["tts"],
            {
                "text": text,
                "language": language,
                "speaker": selected_speaker,
                "output_path": str(output_path),
            },
        )
        result.setdefault("audio_path", str(output_path))
        result.setdefault("model", MAGPIE_TTS_MODEL)
        result.setdefault("speaker", selected_speaker)
        result.setdefault("duration", 0.0)
        result.setdefault("text", text)
        return result


class ModelManager:
    def __init__(self, hooks: ModelHooks):
        self.hooks = hooks
        self.mode = hooks.mode
        self._lock = asyncio.Lock()

    async def llm(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            started = time.perf_counter()
            result = await self.hooks.llm(task, payload)
            result.setdefault("inference_seconds", round(time.perf_counter() - started, 3))
            return result

    async def image(
        self, prompt: str, source_image: Path, output_path: Path, overlay_text: str = ""
    ) -> dict[str, Any]:
        async with self._lock:
            started = time.perf_counter()
            result = await self.hooks.image(prompt, source_image, output_path, overlay_text)
            result.setdefault("inference_seconds", round(time.perf_counter() - started, 3))
            return result

    async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict[str, Any]:
        async with self._lock:
            started = time.perf_counter()
            result = await self.hooks.video(prompt, image_path, output_path)
            result.setdefault("inference_seconds", round(time.perf_counter() - started, 3))
            return result

    async def asr(self, audio_path: Path, language: str) -> dict[str, Any]:
        async with self._lock:
            started = time.perf_counter()
            result = await self.hooks.asr(audio_path, language)
            result.setdefault("inference_seconds", round(time.perf_counter() - started, 3))
            return result

    async def tts(
        self,
        text: str,
        language: str,
        output_path: Path,
        speaker: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            started = time.perf_counter()
            result = await self.hooks.tts(text, language, output_path, speaker)
            result.setdefault("inference_seconds", round(time.perf_counter() - started, 3))
            return result

    async def cleanup(self) -> None:
        async with self._lock:
            await self.hooks.cleanup()


def build_model_manager(mode: str, commands: dict[str, str | None]) -> ModelManager:
    if mode == "command":
        missing = [name for name in ("llm", "image", "video", "asr", "tts") if not commands.get(name)]
        if missing:
            raise ValueError(f"command adapter mode requires commands for: {', '.join(missing)}")
        return ModelManager(CommandModelHooks({key: str(value) for key, value in commands.items()}))
    if mode != "mock":
        raise ValueError("OVERSEAARK_ADAPTER_MODE must be 'mock' or 'command'")
    return ModelManager(MockModelHooks())


async def _run_command(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    args = shlex.split(command)
    if not args:
        raise AdapterError("empty adapter command")
    try:
        timeout = float(os.environ.get("OVERSEAARK_ADAPTER_TIMEOUT", "1200"))
    except ValueError as exc:
        raise AdapterError("OVERSEAARK_ADAPTER_TIMEOUT must be numeric") from exc
    if timeout <= 0:
        raise AdapterError("OVERSEAARK_ADAPTER_TIMEOUT must be greater than zero")
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(payload).encode("utf-8")), timeout=timeout
        )
    except TimeoutError as exc:
        await _terminate_process_group(proc)
        raise AdapterError(
            f"adapter timed out after {timeout:g}s; its process group was terminated"
        ) from exc
    except asyncio.CancelledError:
        await _terminate_process_group(proc)
        raise
    if proc.returncode != 0:
        raise AdapterError(stderr.decode("utf-8", errors="replace").strip() or "adapter failed")
    try:
        result = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterError("adapter command did not return JSON") from exc
    if not isinstance(result, dict):
        raise AdapterError("adapter command returned non-object JSON")
    return result


async def _ffmpeg_degraded_video(
    image_path: Path, output_path: Path, cosmos_error: str
) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AdapterError(f"Cosmos3 failed and ffmpeg is unavailable: {cosmos_error}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        "scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-t",
        "15",
        "-r",
        "24",
        "-an",
        "-movflags",
        "+faststart",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, stderr = await proc.communicate()
    except asyncio.CancelledError:
        await _terminate_process_group(proc)
        raise
    if proc.returncode != 0 or not output_path.is_file():
        raise AdapterError(
            stderr.decode("utf-8", errors="replace").strip()
            or f"Cosmos3 and degraded ffmpeg fallback both failed: {cosmos_error}"
        )
    return {
        "video_path": str(output_path),
        "model": "ffmpeg-degraded-fallback",
        "quality": "degraded",
        "warnings": ["Cosmos3-Edge failed; this is a labeled ffmpeg still-image fallback"],
        "cosmos_error": cosmos_error,
    }


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()


def _write_silent_wav(path: Path) -> float:
    sample_rate = 16_000
    frame_count = 1600
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frame_count)
    return frame_count / sample_rate


def _box(name: bytes, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + name + payload


def _minimal_mp4() -> bytes:
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    free = _box(b"free", b"OverseaArk mock video")
    mdat = _box(b"mdat", b"\x00\x00\x00\x00")
    return ftyp + free + mdat
