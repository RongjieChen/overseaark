from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import shutil
import signal
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from .adapters import DEFAULT_TTS_SPEAKERS, ModelManager
from .models import CampaignStatus, STAGE_ORDER, StageName, StageStatus
from .store import Store

QC_SIMILARITY_THRESHOLD = 0.75


class CampaignCancelled(RuntimeError):
    pass


class ArtifactBoundaryError(ValueError):
    pass


class CampaignRunner:
    def __init__(self, store: Store, model_manager: ModelManager, artifacts_dir: Path):
        self.store = store
        self.model_manager = model_manager
        self.artifacts_dir = artifacts_dir

    async def run(self, campaign_id: str, from_stage: StageName = STAGE_ORDER[0]) -> None:
        campaign = self.store.get_campaign(campaign_id)
        artifacts: dict[str, Any] = dict(campaign.artifacts)
        context: dict[str, Any] = {"campaign": campaign, "artifacts": artifacts}
        self.store.set_campaign_status(campaign_id, CampaignStatus.running)
        self.store.add_event(campaign_id, "campaign.started", f"Campaign started from {from_stage.value}")

        for stage in STAGE_ORDER[STAGE_ORDER.index(from_stage) :]:
            if self._is_cancelled(campaign_id):
                self._skip_remaining(campaign_id, stage)
                return

            self.store.set_campaign_status(campaign_id, CampaignStatus.running, current_stage=stage)
            self.store.add_event(campaign_id, "stage.started", f"{stage.value} started", stage)
            try:
                ok, output, error = await self._run_stage_with_retry(campaign_id, stage, context)
            except CampaignCancelled:
                self._skip_remaining(campaign_id, stage)
                return
            if not ok:
                if output:
                    artifacts[stage.value] = output
                    context["artifacts"] = artifacts
                self._finish_after_failure(campaign_id, stage, artifacts, error)
                return
            artifacts[stage.value] = output
            context["artifacts"] = artifacts
            self.store.set_campaign_status(
                campaign_id,
                CampaignStatus.running,
                current_stage=stage,
                artifacts=artifacts,
            )
            self.store.add_event(campaign_id, "stage.succeeded", f"{stage.value} succeeded", stage, output)

        self.store.set_campaign_status(campaign_id, CampaignStatus.completed, artifacts=artifacts)
        self.store.add_event(campaign_id, "campaign.completed", "Campaign completed", payload=artifacts)

    async def _run_stage_with_retry(
        self,
        campaign_id: str,
        stage: StageName,
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        last_error: str | None = None
        last_output: dict[str, Any] = {}
        for _ in range(2):
            attempts = self.store.increment_stage_attempts(campaign_id, stage)
            self.store.mark_stage(campaign_id, stage, StageStatus.running, attempts=attempts)
            try:
                output = await self._stage_handlers()[stage](context)
                last_output = output
                if self._is_cancelled(campaign_id):
                    raise CampaignCancelled
                self._validate_stage_output(stage, output, context)
            except CampaignCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - stage failures are persisted as campaign state.
                last_error = str(exc)
                if isinstance(exc, ArtifactBoundaryError):
                    last_output = {}
                self.store.add_event(
                    campaign_id,
                    "stage.retry" if attempts == 1 else "stage.failed",
                    f"{stage.value} failed on attempt {attempts}: {last_error}",
                    stage,
                    {"attempts": attempts, "error": last_error},
                )
                if attempts >= 2:
                    self.store.mark_stage(
                        campaign_id,
                        stage,
                        StageStatus.failed,
                        attempts=attempts,
                        error=last_error,
                        output=last_output or None,
                    )
                    return False, last_output, last_error
                continue
            self.store.mark_stage(campaign_id, stage, StageStatus.succeeded, attempts=attempts, output=output)
            return True, output, None
        return False, {}, last_error

    def _stage_handlers(self) -> dict[StageName, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]:
        return {
            StageName.market_positioning: self._market_positioning,
            StageName.buyer_persona: self._buyer_persona,
            StageName.multilingual_copy: self._multilingual_copy,
            StageName.visual_design: self._visual_design,
            StageName.media_production: self._media_production,
            StageName.quality_packaging: self._quality_packaging,
        }

    def _validate_stage_output(
        self, stage: StageName, output: dict[str, Any], context: dict[str, Any]
    ) -> None:
        if not isinstance(output, dict):
            raise ValueError(f"{stage.value} adapter returned a non-object result")
        package_dir = self.artifacts_dir / context["campaign"].id
        if stage == StageName.market_positioning:
            _require_keys(output, stage, "positioning", "differentiators", "market_hypotheses")
        elif stage == StageName.buyer_persona:
            _require_keys(output, stage, "personas")
            if not isinstance(output["personas"], list) or not output["personas"]:
                raise ValueError("buyer_persona.personas must be a non-empty list")
        elif stage == StageName.multilingual_copy:
            _require_keys(output, stage, "copy")
            copy = output["copy"]
            if not isinstance(copy, dict):
                raise ValueError("multilingual_copy.copy must be an object")
            required = (
                "title",
                "headline",
                "selling_points",
                "detail",
                "body",
                "outreach_email",
                "video_script",
                "cta",
            )
            for language in context["campaign"].languages:
                localized = copy.get(language)
                if not isinstance(localized, dict):
                    raise ValueError(f"multilingual_copy.copy missing language {language}")
                missing = [key for key in required if key not in localized]
                if missing:
                    raise ValueError(
                        f"multilingual_copy.copy.{language} missing keys: {', '.join(missing)}"
                    )
        elif stage == StageName.visual_design:
            _require_file_in_dir(output, stage, "image_path", package_dir)
        elif stage == StageName.media_production:
            _require_keys(output, stage, "audio", "video")
            audio = output["audio"]
            for language in context["campaign"].languages:
                if not isinstance(audio, dict) or not isinstance(audio.get(language), dict):
                    raise ValueError(f"media_production.audio missing language {language}")
                _require_file_in_dir(audio[language], stage, "audio_path", package_dir)
            if not isinstance(output["video"], dict):
                raise ValueError("media_production.video must be an object")
            _require_file_in_dir(output["video"], stage, "video_path", package_dir)
            if output["video"].get("quality") == "degraded":
                raise ValueError(
                    "Cosmos3-Edge failed; retained a labeled ffmpeg fallback as a partial artifact"
                )
        elif stage == StageName.quality_packaging:
            _require_keys(output, stage, "qc", "manifest_path", "qc_report_path", "zip_path")
            for key in ("manifest_path", "qc_report_path", "zip_path"):
                _require_file_in_dir(output, stage, key, package_dir)
            if output["qc"].get("passed") is not True:
                raise ValueError("quality_packaging failed the ASR/TTS similarity threshold")

    async def _market_positioning(self, context: dict[str, Any]) -> dict[str, Any]:
        campaign = context["campaign"]
        return await self.model_manager.llm(
            StageName.market_positioning.value,
            {
                "description": campaign.description,
                "source_market": campaign.source_market,
                "target_markets": campaign.target_markets,
                "languages": campaign.languages,
                "product_image_path": campaign.product_image_path,
            },
        )

    async def _buyer_persona(self, context: dict[str, Any]) -> dict[str, Any]:
        campaign = context["campaign"]
        return await self.model_manager.llm(
            StageName.buyer_persona.value,
            {
                "description": campaign.description,
                "positioning": context["artifacts"][StageName.market_positioning.value],
            },
        )

    async def _multilingual_copy(self, context: dict[str, Any]) -> dict[str, Any]:
        campaign = context["campaign"]
        return await self.model_manager.llm(
            StageName.multilingual_copy.value,
            {
                "description": campaign.description,
                "languages": campaign.languages,
                "positioning": context["artifacts"][StageName.market_positioning.value],
                "personas": context["artifacts"][StageName.buyer_persona.value],
            },
        )

    async def _visual_design(self, context: dict[str, Any]) -> dict[str, Any]:
        campaign = context["campaign"]
        output_path = self.artifacts_dir / campaign.id / "visual_design.png"
        copy = context["artifacts"][StageName.multilingual_copy.value]["copy"]
        prompt = f"Cross-border ad visual for {copy['en']['headline']}"
        return await self.model_manager.image(
            prompt,
            Path(campaign.product_image_path),
            output_path,
            copy["en"]["headline"],
        )

    async def _media_production(self, context: dict[str, Any]) -> dict[str, Any]:
        campaign = context["campaign"]
        copy = context["artifacts"][StageName.multilingual_copy.value]["copy"]
        visual_path = Path(context["artifacts"][StageName.visual_design.value]["image_path"])
        audio: dict[str, Any] = {}
        for language in campaign.languages:
            audio_path = self.artifacts_dir / campaign.id / f"voice_{language}.wav"
            audio[language] = await self.model_manager.tts(
                copy[language]["video_script"],
                language,
                audio_path,
                DEFAULT_TTS_SPEAKERS.get(language),
            )
        video_path = self.artifacts_dir / campaign.id / "campaign_video.mp4"
        model_video_path = (
            self.artifacts_dir / campaign.id / "cosmos_video.mp4"
            if self.model_manager.mode == "command"
            else video_path
        )
        video = await self.model_manager.video(
            "15 second localized product ad", visual_path, model_video_path
        )
        if self.model_manager.mode == "command":
            narration_language = "en" if "en" in audio else campaign.languages[0]
            subtitle_path = self.artifacts_dir / campaign.id / f"subtitles_{narration_language}.srt"
            subtitle_text = copy[narration_language]["video_script"]
            await _compose_video(
                Path(video["video_path"]),
                Path(audio[narration_language]["audio_path"]),
                subtitle_text,
                subtitle_path,
                video_path,
            )
            video["model_video_path"] = video["video_path"]
            video["video_path"] = str(video_path)
            video["subtitle_path"] = str(subtitle_path)
            video["narration_language"] = narration_language
            video["ffmpeg_composed"] = True
        return {"audio": audio, "video": video}

    async def _quality_packaging(self, context: dict[str, Any]) -> dict[str, Any]:
        campaign = context["campaign"]
        package_dir = self.artifacts_dir / campaign.id
        manifest_path = package_dir / "manifest.json"
        qc_report_path = package_dir / "qc_report.json"
        zip_path = package_dir / "export.zip"
        media = context["artifacts"][StageName.media_production.value]
        audio_checks = await self._qc_audio(campaign.languages, media["audio"], package_dir)
        video = media["video"]
        warnings = list(video.get("warnings", []))
        if video.get("quality") == "degraded":
            warnings.append("Video generated with degraded Cosmos fallback quality")
        qc_report = {
            "threshold": QC_SIMILARITY_THRESHOLD,
            "audio": audio_checks,
            "video": {
                "quality": video.get("quality", "standard"),
                "warnings": warnings,
            },
            "passed": all(item["passed"] for item in audio_checks.values()),
            "deterministic_checks": [
                "requested language copy exists",
                "poster, narration, subtitle, and video files exist",
                "ASR round-trip similarity meets threshold",
                "archive manifest records model provenance",
            ],
            "offline_inference": True,
        }
        current_campaign = self.store.get_campaign(campaign.id)
        model_audit = _model_audit()
        manifest = {
            "campaign_id": campaign.id,
            "name": campaign.name,
            "languages": campaign.languages,
            "artifacts": context["artifacts"],
            "qc": qc_report,
            "offline_inference": True,
            "model_manifest": model_audit,
            "model_calls": _collect_model_calls(
                {
                    "artifacts": context["artifacts"],
                    "quality_audio_checks": audio_checks,
                }
            ),
            "stage_attempts": {
                stage.name.value: stage.attempts for stage in current_campaign.stages
            },
        }
        packaging_output = {
            "qc": qc_report,
            "manifest_path": str(manifest_path),
            "qc_report_path": str(qc_report_path),
            "zip_path": str(zip_path),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        qc_report_path.write_text(json.dumps(qc_report, indent=2), encoding="utf-8")
        stage_payloads = {
            **context["artifacts"],
            StageName.quality_packaging.value: packaging_output,
        }
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, "manifest.json")
            archive.write(qc_report_path, "qc_report.json")
            source_image = Path(campaign.product_image_path)
            archive.write(source_image, "source_product_image" + source_image.suffix)
            archive.write(source_image, "source_image" + source_image.suffix)
            for stage, payload in stage_payloads.items():
                archive.writestr(f"stages/{stage}.json", json.dumps(payload, indent=2))
            copy = context["artifacts"][StageName.multilingual_copy.value]["copy"]
            for language in campaign.languages:
                archive.writestr(f"copy/{language}.json", json.dumps(copy[language], indent=2))
            visual = _resolve_file_in_dir(
                context["artifacts"][StageName.visual_design.value]["image_path"],
                package_dir,
                StageName.visual_design,
                "image_path",
            )
            archive.write(visual, visual.name)
            archive.write(visual, "poster.png")
            video = _resolve_file_in_dir(
                media["video"]["video_path"], package_dir, StageName.media_production, "video_path"
            )
            archive.write(video, "campaign_video.mp4")
            archive.write(video, "video.mp4")
            for language, item in media["audio"].items():
                audio_path = _resolve_file_in_dir(
                    item["audio_path"], package_dir, StageName.media_production, "audio_path"
                )
                archive.write(audio_path, f"voice_{language}.wav")
                archive.write(audio_path, f"audio/{language}.wav")
        return packaging_output

    async def _qc_audio(
        self,
        languages: list[str],
        audio: dict[str, Any],
        package_dir: Path,
    ) -> dict[str, dict[str, Any]]:
        checks: dict[str, dict[str, Any]] = {}
        for language in languages:
            item = audio[language]
            reference_text = item["text"]
            audio_path = _resolve_file_in_dir(
                item["audio_path"], package_dir, StageName.media_production, "audio_path"
            )
            transcript = await self.model_manager.asr(audio_path, language)
            similarity = _normalized_similarity(reference_text, transcript["text"])
            retries = 0
            if similarity < QC_SIMILARITY_THRESHOLD:
                retries = 1
                retry_path = Path(item["audio_path"]).with_name(f"voice_{language}_retry.wav")
                replacement = await self.model_manager.tts(
                    reference_text,
                    language,
                    retry_path,
                    item.get("speaker") or DEFAULT_TTS_SPEAKERS.get(language),
                )
                audio[language] = replacement
                item = replacement
                audio_path = _resolve_file_in_dir(
                    item["audio_path"], package_dir, StageName.media_production, "audio_path"
                )
                transcript = await self.model_manager.asr(audio_path, language)
                similarity = _normalized_similarity(reference_text, transcript["text"])
            checks[language] = {
                "reference_text": reference_text,
                "transcript": transcript["text"],
                "detected_language": transcript.get("detected_language", transcript.get("language")),
                "model": transcript.get("model"),
                "inference_seconds": transcript.get("inference_seconds"),
                "similarity": similarity,
                "threshold": QC_SIMILARITY_THRESHOLD,
                "retries": retries,
                "passed": similarity >= QC_SIMILARITY_THRESHOLD,
                "speaker": item.get("speaker"),
                "duration": item.get("duration"),
            }
        return checks

    def _finish_after_failure(
        self,
        campaign_id: str,
        failed_stage: StageName,
        artifacts: dict[str, Any],
        error: str | None,
    ) -> None:
        failed_index = STAGE_ORDER.index(failed_stage)
        for stage in STAGE_ORDER[failed_index + 1 :]:
            self.store.mark_stage(campaign_id, stage, StageStatus.skipped, error="Skipped after failure")
        status = CampaignStatus.partial if artifacts else CampaignStatus.failed
        self.store.set_campaign_status(
            campaign_id,
            status,
            current_stage=None,
            error=error,
            artifacts=artifacts,
        )
        self.store.add_event(
            campaign_id,
            f"campaign.{status.value}",
            f"Campaign {status.value}: {error}",
            failed_stage,
            {"error": error},
        )

    def _skip_remaining(self, campaign_id: str, current_stage: StageName) -> None:
        current_index = STAGE_ORDER.index(current_stage)
        for stage in STAGE_ORDER[current_index:]:
            self.store.mark_stage(campaign_id, stage, StageStatus.skipped, error="Cancelled")
        self.store.set_campaign_status(campaign_id, CampaignStatus.cancelled, current_stage=None)
        self.store.add_event(campaign_id, "campaign.cancelled", "Campaign cancelled")

    def _is_cancelled(self, campaign_id: str) -> bool:
        return self.store.is_cancel_requested(campaign_id)


def _normalized_similarity(reference: str, candidate: str) -> float:
    normalized_reference = "".join(_tokens(reference))
    normalized_candidate = "".join(_tokens(candidate))
    if not normalized_reference and not normalized_candidate:
        return 1.0
    if not normalized_reference or not normalized_candidate:
        return 0.0
    return difflib.SequenceMatcher(None, normalized_reference, normalized_candidate).ratio()


def _tokens(value: str) -> list[str]:
    return re.findall(r"[\w]+", value.lower(), flags=re.UNICODE)


def _require_keys(output: dict[str, Any], stage: StageName, *keys: str) -> None:
    missing = [key for key in keys if key not in output]
    if missing:
        raise ValueError(f"{stage.value} output missing keys: {', '.join(missing)}")


def _require_file(output: dict[str, Any], stage: StageName, key: str) -> None:
    value = output.get(key)
    if not isinstance(value, str) or not Path(value).is_file():
        raise ValueError(f"{stage.value}.{key} does not reference an existing file")


def _require_file_in_dir(
    output: dict[str, Any],
    stage: StageName,
    key: str,
    directory: Path,
) -> None:
    _resolve_file_in_dir(output.get(key), directory, stage, key)


def _resolve_file_in_dir(value: Any, directory: Path, stage: StageName, key: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{stage.value}.{key} does not reference an existing file")
    try:
        resolved = Path(value).resolve(strict=True)
        resolved.relative_to(directory.resolve())
    except FileNotFoundError as exc:
        raise ValueError(f"{stage.value}.{key} does not reference an existing file") from exc
    except ValueError as exc:
        raise ArtifactBoundaryError(
            f"{stage.value}.{key} points outside campaign artifact directory"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"{stage.value}.{key} does not reference an existing file")
    return resolved


def _model_audit() -> list[dict[str, Any]]:
    manifest_path = Path(__file__).resolve().parents[2] / "model-manifest.lock.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        {
            "id": item["id"],
            "source": item["source"],
            "revision": item.get("revision"),
            "upstream_revision": item.get("upstream_revision"),
            "local_dir": item["local_dir"],
            "required": item.get("required", True),
            "license": item.get("license"),
        }
        for item in data["models"]
    ]


def _collect_model_calls(value: Any, path: str = "") -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "model" in value:
            calls.append(
                {
                    "artifact": path or "root",
                    "model": value.get("model"),
                    "inference_seconds": value.get("inference_seconds"),
                    "quality": value.get("quality", "standard"),
                }
            )
        for key, item in value.items():
            calls.extend(_collect_model_calls(item, f"{path}.{key}".strip(".")))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            calls.extend(_collect_model_calls(item, f"{path}[{index}]"))
    return calls


async def _compose_video(
    source_video: Path,
    narration_audio: Path,
    subtitle_text: str,
    subtitle_path: Path,
    output_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to compose narration and subtitles")
    clean_subtitle = re.sub(r"\s+", " ", subtitle_text).strip()
    subtitle_path.write_text(
        f"1\n00:00:00,000 --> 00:00:15,000\n{clean_subtitle}\n",
        encoding="utf-8",
    )
    escaped_subtitle = (
        str(subtitle_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    )
    proc = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(source_video),
        "-i",
        str(narration_audio),
        "-vf",
        f"scale=854:480:force_original_aspect_ratio=decrease,"
        f"pad=854:480:(ow-iw)/2:(oh-ih)/2,subtitles='{escaped_subtitle}',format=yuv420p",
        "-af",
        "apad",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-t",
        "15",
        "-r",
        "24",
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
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
        raise
    if proc.returncode != 0 or not output_path.is_file():
        raise RuntimeError(
            stderr.decode("utf-8", errors="replace").strip()
            or "ffmpeg failed to compose the final campaign video"
        )
