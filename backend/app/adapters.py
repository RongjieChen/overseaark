from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import shutil
import shlex
import tempfile
import time
import uuid
import wave
from abc import ABC
from pathlib import Path
from typing import Any


LLM_MODEL = "nvidia/Qwen3.6-35B-A3B-NVFP4"
IMAGE_MODEL = "stepfun-ai/Step1X-Edit-v1p2"
VIDEO_MODEL = "nvidia/Cosmos3-Edge"
NEMOTRON_ASR_MODEL = "nvidia/nemotron-3.5-asr-streaming-0.6b"
MAGPIE_TTS_MODEL = "nvidia/magpie_tts_multilingual_357m"
DEFAULT_TTS_SPEAKERS = {"zh": "Sofia", "en": "Jason", "ja": "Aria"}

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
)


class AdapterError(RuntimeError):
    pass


class _ResidentRequestError(AdapterError):
    def __init__(self, message: str, *, error_type: str, restart_worker: bool):
        super().__init__(message)
        self.error_type = error_type
        self.restart_worker = restart_worker


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
            localized_copy = {
                "zh": {
                    "headline": "让好产品轻松走向全球",
                    "title": "全球市场本地化发布方案",
                    "selling_points": ["可信的本地化表达", "清晰的产品价值", "快速生成营销素材"],
                    "detail": "围绕目标市场需求，用自然中文呈现产品价值、使用场景与购买理由。",
                    "body": "从产品信息出发，形成适合目标市场的定位、卖点、触达文案与演示素材。",
                    "outreach_email": "您好，我们为这款产品准备了完整的本地化上市方案，期待与您进一步交流。",
                    "video_script": "本地生成多语素材，让好产品更快走向全球。",
                    "cta": "立即了解",
                },
                "en": {
                    "headline": "Launch a trusted product story worldwide",
                    "title": "Localized global market launch",
                    "selling_points": ["Localized trust", "Clear product value", "Fast asset creation"],
                    "detail": "Present the product value, use cases, and purchase reasons in natural English.",
                    "body": "Turn product information into positioning, benefits, outreach copy, and demo-ready assets.",
                    "outreach_email": "Hello, we prepared a complete localized launch package and would welcome a conversation.",
                    "video_script": "Create localized assets locally and launch worldwide faster.",
                    "cta": "Learn more",
                },
                "ja": {
                    "headline": "信頼できる商品ストーリーを世界へ",
                    "title": "海外市場向けローカライズ提案",
                    "selling_points": ["自然なローカライズ", "明確な商品価値", "素早い素材制作"],
                    "detail": "商品価値や利用シーン、購入理由を自然な日本語でわかりやすく伝えます。",
                    "body": "商品情報から市場ポジション、訴求点、営業文、デモ素材まで一貫して制作します。",
                    "outreach_email": "こんにちは。本商品の市場展開に向けたローカライズ資料をご用意しました。ぜひご相談ください。",
                    "video_script": "多言語素材をローカルで制作し、世界へ素早く届けます。",
                    "cta": "詳しく見る",
                },
            }
            return {
                "copy": {language: localized_copy.get(language, localized_copy["en"]) for language in languages},
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

    def __init__(
        self,
        commands: dict[str, str],
        *,
        resident_adapters: set[str] | None = None,
        keep_vllm_resident: bool | None = None,
    ):
        self.commands = commands
        self.resident_adapters = (
            _default_resident_adapters() if resident_adapters is None else resident_adapters
        )
        self.keep_vllm_resident = (
            os.environ.get("OVERSEAARK_KEEP_VLLM_RESIDENT", "0") == "1"
            if keep_vllm_resident is None
            else keep_vllm_resident
        )
        self._resident = {
            name: ResidentCommandAdapter(name, commands[name])
            for name in self.resident_adapters
            if name in commands
        }

    async def _set_llm_active(self, active: bool) -> None:
        if not active and self.keep_vllm_resident:
            return
        if not active:
            await self._stop_llm()
            return
        control = self.commands.get("llm_control")
        if control:
            await _run_control_command(control, "start")

    async def _stop_llm(self) -> None:
        control = self.commands.get("llm_control")
        if control:
            await _run_control_command(control, "stop")

    async def warmup(self, adapters: set[str] | None = None) -> dict[str, dict[str, Any]]:
        selected = set(self._resident) if adapters is None else adapters
        statuses: dict[str, dict[str, Any]] = {}
        warmed: list[str] = []
        try:
            for name in sorted(selected):
                worker = self._resident.get(name)
                if worker is None:
                    continue
                statuses[name] = await worker.warmup()
                warmed.append(name)
        except Exception:
            for name in warmed:
                worker = self._resident.get(name)
                if worker is not None:
                    await worker.aclose()
            raise
        return statuses

    async def warmup_llm(self) -> dict[str, Any]:
        await self._set_llm_active(True)
        return {"ready": True, "resident": self.keep_vllm_resident}

    async def prepare_idle(self) -> dict[str, Any]:
        try:
            return {"llm": await self.warmup_llm(), "workers": await self.warmup()}
        except Exception:
            for worker in self._resident.values():
                await worker.aclose()
            await self._stop_llm()
            raise

    async def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "resident_adapters": sorted(self._resident),
            "workers": {name: worker.status() for name, worker in sorted(self._resident.items())},
            "keep_vllm_resident": self.keep_vllm_resident,
        }

    async def llm(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self._set_llm_active(True)
        return await _run_command(self.commands["llm"], {"task": task, **payload})

    async def image(
        self, prompt: str, source_image: Path, output_path: Path, overlay_text: str = ""
    ) -> dict[str, Any]:
        await self._set_llm_active(False)
        payload = {
            "prompt": prompt,
            "source_image": str(source_image),
            "output_path": str(output_path),
            "overlay_text": overlay_text,
        }
        result = await self._run_adapter("image", payload)
        result.setdefault("image_path", str(output_path))
        return result

    async def video(self, prompt: str, image_path: Path, output_path: Path) -> dict[str, Any]:
        await self._set_llm_active(False)
        try:
            result = await self._run_adapter(
                "video", {"prompt": prompt, "image_path": str(image_path), "output_path": str(output_path)}
            )
        except AdapterError as exc:
            if os.environ.get("OVERSEAARK_ALLOW_DEGRADED_VIDEO", "1") != "1":
                raise
            result = await _ffmpeg_degraded_video(image_path, output_path, str(exc))
        result.setdefault("video_path", str(output_path))
        return result

    async def asr(self, audio_path: Path, language: str) -> dict[str, Any]:
        await self._set_llm_active(False)
        result = await self._run_adapter("asr", {"audio_path": str(audio_path), "language": language})
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
        await self._set_llm_active(False)
        selected_speaker = speaker or DEFAULT_TTS_SPEAKERS.get(language, "Jason")
        result = await self._run_adapter(
            "tts",
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

    async def cleanup(self) -> None:
        for worker in self._resident.values():
            await worker.aclose()
        await self._stop_llm()

    async def _run_adapter(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        worker = self._resident.get(name)
        if worker is not None:
            return await worker.request(payload)
        return await _run_command(self.commands[name], payload)


class ModelManager:
    def __init__(self, hooks: ModelHooks):
        self.hooks = hooks
        self.mode = hooks.mode
        self._lock = asyncio.Lock()
        self._preparation_state: dict[str, Any] = {
            "status": "ready" if hooks.mode == "mock" else "pending",
            "reason": "mock adapters need no GPU warmup" if hooks.mode == "mock" else "startup",
            "result": {},
            "error": None,
        }

    def preparation_status(self) -> dict[str, Any]:
        return dict(self._preparation_state)

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

    async def warmup_workers(self, adapters: set[str] | None = None) -> dict[str, dict[str, Any]]:
        async with self._lock:
            warmup = getattr(self.hooks, "warmup", None)
            if warmup is None:
                return {}
            return await warmup(adapters)

    async def worker_status(self) -> dict[str, Any]:
        async with self._lock:
            status = getattr(self.hooks, "status", None)
            if status is None:
                return {"mode": self.mode, "resident_adapters": [], "workers": {}}
            return await status()

    async def warmup_llm(self) -> dict[str, Any]:
        async with self._lock:
            warmup_llm = getattr(self.hooks, "warmup_llm", None)
            if warmup_llm is None:
                return {"ready": False, "resident": False}
            return await warmup_llm()

    async def prepare_idle(self, reason: str = "idle") -> dict[str, Any]:
        self._preparation_state.update(status="warming", reason=reason, result={}, error=None)
        try:
            async with self._lock:
                prepare_idle = getattr(self.hooks, "prepare_idle", None)
                if prepare_idle is None:
                    result = {"llm": {"ready": False, "resident": False}, "workers": {}}
                else:
                    result = await prepare_idle()
        except asyncio.CancelledError:
            self._preparation_state.update(
                status="cancelled",
                error="model warmup was cancelled",
            )
            raise
        except Exception as exc:
            self._preparation_state.update(status="degraded", error=str(exc))
            raise
        self._preparation_state.update(status="ready", result=result, error=None)
        return result


def build_model_manager(
    mode: str,
    commands: dict[str, str | None],
    *,
    resident_adapters: str | set[str] | None = None,
    keep_vllm_resident: bool | None = None,
) -> ModelManager:
    if mode == "command":
        missing = [name for name in ("llm", "image", "video", "asr", "tts") if not commands.get(name)]
        if missing:
            raise ValueError(f"command adapter mode requires commands for: {', '.join(missing)}")
        return ModelManager(
            CommandModelHooks(
                {key: str(value) for key, value in commands.items() if value is not None},
                resident_adapters=_parse_resident_adapters(resident_adapters),
                keep_vllm_resident=keep_vllm_resident,
            )
        )
    if mode != "mock":
        raise ValueError("OVERSEAARK_ADAPTER_MODE must be 'mock' or 'command'")
    return ModelManager(MockModelHooks())


def _adapter_timeout() -> float:
    try:
        timeout = float(os.environ.get("OVERSEAARK_ADAPTER_TIMEOUT", "1200"))
    except ValueError as exc:
        raise AdapterError("OVERSEAARK_ADAPTER_TIMEOUT must be numeric") from exc
    if timeout <= 0:
        raise AdapterError("OVERSEAARK_ADAPTER_TIMEOUT must be greater than zero")
    return timeout


def _default_resident_adapters() -> set[str]:
    configured = os.environ.get("OVERSEAARK_RESIDENT_ADAPTERS")
    if configured is None:
        return {"asr", "tts"}
    return _parse_resident_adapters(configured) or set()


def _parse_resident_adapters(value: str | set[str] | None) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, set):
        return set(value)
    names = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = names - {"asr", "tts", "image"}
    if unknown:
        raise ValueError(
            "OVERSEAARK_RESIDENT_ADAPTERS supports only: asr, tts, image"
        )
    return names


async def _run_command(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    args = shlex.split(command)
    if not args:
        raise AdapterError("empty adapter command")
    timeout = _adapter_timeout()
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
    result = _parse_command_stdout(stdout)
    if not isinstance(result, dict):
        raise AdapterError("adapter command returned non-object JSON")
    return result


class ResidentCommandAdapter:
    def __init__(self, name: str, command: str):
        self.name = name
        self.command = command
        self.proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail = ""
        self._starts = 0
        self._ready = False

    async def warmup(self) -> dict[str, Any]:
        await self._ensure_started()
        return {"running": True, "pid": self.proc.pid if self.proc else None, "starts": self._starts}

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            await self._ensure_started()
            assert self.proc is not None
            timeout = _adapter_timeout()
            result = await asyncio.wait_for(self._request_once(payload), timeout=timeout)
        except TimeoutError as exc:
            await self._restart_after_failure()
            raise AdapterError(
                f"resident {self.name} adapter timed out after {_adapter_timeout():g}s; worker was restarted"
            ) from exc
        except asyncio.CancelledError:
            # The worker executes one GPU request at a time. Killing its process
            # group is the only reliable way to ensure cancelled inference does
            # not continue consuming GPU memory behind the campaign task.
            await self.aclose()
            raise
        except _ResidentRequestError as exc:
            if exc.restart_worker:
                await self._restart_after_failure()
                raise AdapterError(
                    f"resident {self.name} adapter failed with {exc.error_type}: {exc}; "
                    "worker was restarted"
                ) from exc
            raise AdapterError(
                f"resident {self.name} adapter rejected the request with {exc.error_type}: {exc}"
            ) from exc
        except (BrokenPipeError, EOFError, ConnectionResetError) as exc:
            await self._restart_after_failure()
            raise AdapterError(f"resident {self.name} adapter exited unexpectedly; worker was restarted") from exc
        if not isinstance(result, dict):
            raise AdapterError(f"resident {self.name} adapter returned non-object JSON")
        return result

    def status(self) -> dict[str, Any]:
        running = self.proc is not None and self.proc.returncode is None
        return {
            "running": running,
            "ready": running and self._ready,
            "pid": self.proc.pid if running and self.proc else None,
            "starts": self._starts,
        }

    async def aclose(self) -> None:
        proc = self.proc
        self.proc = None
        self._ready = False
        if proc is not None and proc.returncode is None:
            await _terminate_process_group(proc)
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None

    async def _ensure_started(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            return
        await self.aclose()
        args = shlex.split(self.command)
        if not args:
            raise AdapterError(f"empty resident {self.name} adapter command")
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            "--resident",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._starts += 1
        self._ready = False
        self._stderr_tail = ""
        self._stderr_task = asyncio.create_task(self._capture_stderr(self.proc))
        try:
            await asyncio.wait_for(self._resident_call({"action": "warmup"}), timeout=_adapter_timeout())
            self._ready = True
        except Exception:
            await self.aclose()
            raise

    async def _request_once(self, payload: dict[str, Any]) -> Any:
        return await self._resident_call({"action": "request", "payload": payload})

    async def _resident_call(self, message: dict[str, Any]) -> Any:
        assert self.proc is not None and self.proc.stdin is not None and self.proc.stdout is not None
        request_id = str(uuid.uuid4())
        envelope = {"request_id": request_id, **message}
        self.proc.stdin.write((json.dumps(envelope) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                detail = self._stderr_tail.strip()
                raise EOFError(detail or f"resident {self.name} adapter closed stdout")
            try:
                response = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if response.get("request_id") != request_id:
                continue
            if response.get("ok") is True:
                return response.get("result", {})
            error = response.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or f"resident {self.name} adapter failed")
                error_type = str(error.get("type") or "AdapterError")
                restart_worker = bool(
                    error.get("restart_worker", error.get("fatal", False))
                )
                raise _ResidentRequestError(
                    message,
                    error_type=error_type,
                    restart_worker=restart_worker,
                )
            raise AdapterError(str(error or f"resident {self.name} adapter failed"))

    async def _restart_after_failure(self) -> None:
        await self.aclose()
        await self._ensure_started()

    async def _capture_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.readline()
            if not chunk:
                return
            self._stderr_tail = (self._stderr_tail + chunk.decode("utf-8", errors="replace"))[-4000:]


async def _run_control_command(command: str, action: str) -> None:
    base_args = shlex.split(command)
    if not base_args:
        raise AdapterError("empty LLM control command")
    args = [*base_args, action]
    # The start action intentionally daemonizes the vLLM server. A daemon can
    # briefly inherit its launcher's stdout/stderr file descriptors, so PIPE +
    # communicate() may wait for the daemon instead of the already-exited
    # control process. A seekable temporary file preserves failure diagnostics
    # without tying completion to pipe EOF from grandchildren.
    with tempfile.TemporaryFile() as control_output:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=control_output,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            await asyncio.wait_for(
                proc.wait(),
                timeout=float(os.environ.get("OVERSEAARK_VLLM_STARTUP_TIMEOUT", "1200")),
            )
        except TimeoutError as exc:
            await _terminate_process_group(proc)
            raise AdapterError(f"LLM control timed out while requesting {action}") from exc
        except asyncio.CancelledError:
            await _terminate_process_group(proc)
            raise
        if proc.returncode != 0:
            control_output.seek(0)
            detail = control_output.read().decode("utf-8", errors="replace").strip()
            raise AdapterError(detail or f"LLM control failed while requesting {action}")


def _parse_command_stdout(stdout: bytes) -> Any:
    decoded = stdout.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(decoded)
    except json.JSONDecodeError as exc:
        # NeMo and a few CUDA libraries write progress information to stdout
        # even when their Python logging is configured for stderr. Adapter
        # scripts own the final line, so accept only that line as the protocol
        # result instead of scanning arbitrary diagnostics for JSON.
        final_line = decoded.rsplit("\n", 1)[-1] if decoded else ""
        try:
            return json.loads(final_line)
        except json.JSONDecodeError:
            raise AdapterError("adapter command did not end with a JSON result") from exc


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
