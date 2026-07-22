from __future__ import annotations

import copy
import json
import re
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException

from .models import DEFAULT_LANGUAGES, CampaignDetail, StageName

SUPPORTED_LANGUAGES = set(DEFAULT_LANGUAGES)
LANGUAGE_DECLARATION_KEYS = {"language", "detected_language", "narration_language"}
PATH_REFERENCE_KEYS = {"artifact", "archive_path", "filename", "path"}
VIDEO_ASSET_KEYS = {
    "ffmpeg_composed",
    "model_video_path",
    "narration_language",
    "subtitle_path",
    "video_path",
}
_DROP = object()
ASSET_FILENAMES = {
    "source": "source-product-image",
    "poster": "poster.png",
    "video": "campaign-video.mp4",
    "qc": "qc-report.json",
}


def validate_export_language(language: str | None) -> str | None:
    if language is None:
        return None
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported language; supported: zh,en,ja")
    return language


def export_filename(campaign: CampaignDetail, language: str | None) -> str:
    stem = _filename_slug(campaign.name or campaign.id)
    if language:
        return f"overseaark-{stem}-{language}.zip"
    return f"overseaark-{stem}-all-languages.zip"


def asset_file(campaign: CampaignDetail, artifacts_dir: Path, asset_key: str) -> tuple[Path, str]:
    package_dir = artifacts_dir / campaign.id
    if asset_key == "source":
        source = _resolve_exact_campaign_file(
            campaign.product_image_path,
            artifacts_dir.parent / "uploads" / "campaigns",
        )
        return source, f"{ASSET_FILENAMES[asset_key]}{source.suffix}"
    if asset_key == "poster":
        visual_path = campaign.artifacts.get(StageName.visual_design.value, {}).get("image_path")
        return _resolve_artifact_file(visual_path, package_dir), ASSET_FILENAMES[asset_key]
    if asset_key == "video":
        video_path = (
            campaign.artifacts.get(StageName.media_production.value, {})
            .get("video", {})
            .get("video_path")
        )
        return _resolve_artifact_file(video_path, package_dir), ASSET_FILENAMES[asset_key]
    if asset_key == "qc":
        qc_path = (
            campaign.artifacts.get(StageName.quality_packaging.value, {})
            .get("qc_report_path")
        )
        return _resolve_artifact_file(qc_path, package_dir), ASSET_FILENAMES[asset_key]
    if asset_key.startswith("audio-"):
        language = asset_key.removeprefix("audio-")
        validate_export_language(language)
        audio_path = (
            campaign.artifacts.get(StageName.media_production.value, {})
            .get("audio", {})
            .get(language, {})
            .get("audio_path")
        )
        return _resolve_artifact_file(audio_path, package_dir), f"audio-{language}.wav"
    raise HTTPException(status_code=404, detail="Campaign asset not found")


def build_campaign_export_zip(
    campaign: CampaignDetail,
    artifacts_dir: Path,
    language: str | None = None,
    artifacts: dict[str, Any] | None = None,
) -> Path:
    language = validate_export_language(language)
    package_dir = artifacts_dir / campaign.id
    package_dir.mkdir(parents=True, exist_ok=True)
    active_artifacts = artifacts or campaign.artifacts
    zip_path = package_dir / (f"export-{language}.zip" if language else "export.zip")
    requested_languages = _requested_languages(campaign)
    if language and language not in requested_languages:
        raise HTTPException(status_code=422, detail="Language was not requested for this campaign")
    export_languages = [language] if language else requested_languages
    media = active_artifacts.get(StageName.media_production.value, {})
    video_metadata = media.get("video", {})
    narration_language = (
        video_metadata.get("narration_language") if isinstance(video_metadata, dict) else None
    )
    video = _optional_artifact_file(
        video_metadata.get("video_path") if isinstance(video_metadata, dict) else None,
        package_dir,
    )
    include_video = video is not None and (
        language is None or narration_language == language
    )
    manifest = _manifest(
        campaign,
        active_artifacts,
        language,
        package_dir,
        requested_languages=requested_languages,
        include_video=include_video,
    )
    _annotate_video_export(
        manifest,
        language=language,
        video_included=include_video,
        narration_language=narration_language,
    )
    qc_report = _qc_report(
        campaign,
        active_artifacts,
        language,
        package_dir,
        requested_languages=requested_languages,
        include_video=include_video,
    )
    temporary_path = zip_path.with_name(f".{zip_path.name}.{uuid.uuid4().hex}.tmp")

    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            _write_json(archive, "manifest.json", manifest)
            _write_json(archive, "qc_report.json", qc_report)
            _write_json(archive, "shared/qc_report.json", qc_report)

            source = _optional_exact_campaign_file(
                campaign.product_image_path,
                artifacts_dir.parent / "uploads" / "campaigns",
            )
            if source:
                _write_file(archive, source, f"shared/source_image{source.suffix}")
                _write_file(archive, source, f"source_image{source.suffix}")
                _write_file(archive, source, f"source_product_image{source.suffix}")

            visual = _optional_artifact_file(
                active_artifacts.get(StageName.visual_design.value, {}).get("image_path"),
                package_dir,
            )
            if visual:
                _write_file(archive, visual, f"shared/{visual.name}")
                _write_file(archive, visual, "shared/poster.png")
                _write_file(archive, visual, visual.name)
                _write_file(archive, visual, "poster.png")

            if include_video and video:
                _write_file(archive, video, "shared/video.mp4")
                _write_file(archive, video, "campaign_video.mp4")
                _write_file(archive, video, "video.mp4")

            for stage_name, output in _filtered_stage_payloads(
                active_artifacts,
                language,
                requested_languages=requested_languages,
                include_video=include_video,
            ).items():
                _write_json(archive, f"stages/{stage_name}.json", output)

            copy_by_language = active_artifacts.get(StageName.multilingual_copy.value, {}).get(
                "copy", {}
            )
            audio_by_language = media.get("audio", {})
            for export_language in export_languages:
                archive.writestr(f"{export_language}/", b"")
                localized = copy_by_language.get(export_language)
                if localized is not None:
                    _write_json(archive, f"{export_language}/copy.json", localized)
                    _write_json(archive, f"copy/{export_language}.json", localized)
                audio_path = _optional_artifact_file(
                    audio_by_language.get(export_language, {}).get("audio_path"),
                    package_dir,
                )
                if audio_path:
                    _write_file(archive, audio_path, f"{export_language}/audio.wav")
                    _write_file(archive, audio_path, f"audio/{export_language}.wav")
                    _write_file(archive, audio_path, f"voice_{export_language}.wav")
                if include_video and video and narration_language == export_language:
                    _write_file(archive, video, f"{export_language}/video.mp4")
        temporary_path.replace(zip_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return zip_path


def _manifest(
    campaign: CampaignDetail,
    artifacts: dict[str, Any],
    language: str | None,
    package_dir: Path,
    *,
    requested_languages: list[str],
    include_video: bool,
) -> dict[str, Any]:
    existing = _read_existing_json(
        artifacts.get(StageName.quality_packaging.value, {}).get("manifest_path"),
        package_dir,
    )
    if isinstance(existing, dict):
        manifest = copy.deepcopy(existing)
    else:
        manifest = {
            "campaign_id": campaign.id,
            "name": campaign.name,
            "status": campaign.status.value,
            "error": campaign.error,
            "languages": campaign.languages,
            "artifacts": artifacts,
            "stages": [stage.model_dump(mode="json") for stage in campaign.stages],
            "quality": "partial" if campaign.status.value == "partial" else "complete",
            "offline_inference": True,
        }
    manifest = _filter_language_data(
        manifest,
        language,
        requested_languages=requested_languages,
        include_video=include_video,
    )
    manifest["languages"] = [language] if language else requested_languages
    manifest["export_language"] = language or "all"
    manifest["export_layout_version"] = 2
    return manifest


def _qc_report(
    campaign: CampaignDetail,
    artifacts: dict[str, Any],
    language: str | None,
    package_dir: Path,
    *,
    requested_languages: list[str],
    include_video: bool,
) -> dict[str, Any]:
    existing = _read_existing_json(
        artifacts.get(StageName.quality_packaging.value, {}).get("qc_report_path"),
        package_dir,
    )
    if isinstance(existing, dict):
        report = copy.deepcopy(existing)
    else:
        report = {
            "passed": campaign.status.value == "completed",
            "campaign_status": campaign.status.value,
            "error": campaign.error,
            "offline_inference": True,
        }
    return _filter_language_data(
        report,
        language,
        requested_languages=requested_languages,
        include_video=include_video,
    )


def _filtered_stage_payloads(
    artifacts: dict[str, Any],
    language: str | None,
    *,
    requested_languages: list[str],
    include_video: bool,
) -> dict[str, Any]:
    return {
        stage_name: _filter_language_data(
            output,
            language,
            requested_languages=requested_languages,
            include_video=include_video,
        )
        for stage_name, output in artifacts.items()
    }


def _filter_language_data(
    value: Any,
    language: str | None,
    *,
    requested_languages: list[str],
    include_video: bool,
) -> Any:
    allowed_languages = {language} if language else set(requested_languages)
    filtered = _filter_language_node(value, allowed_languages, include_video=include_video)
    if filtered is _DROP:
        return {}
    return filtered


def _filter_language_node(
    value: Any,
    allowed_languages: set[str],
    *,
    include_video: bool,
) -> Any:
    if isinstance(value, dict):
        if _declares_disallowed_language(value, allowed_languages):
            return _DROP
        if _references_disallowed_language(value, allowed_languages):
            return _DROP
        if not include_video and _references_video_asset(value):
            return _DROP
        filtered: dict[str, Any] = {}
        for key, item in value.items():
            if key in SUPPORTED_LANGUAGES and key not in allowed_languages:
                continue
            if key in {"languages", "target_languages"} and isinstance(item, list):
                filtered[key] = [
                    candidate for candidate in item if candidate in allowed_languages
                ]
                continue
            if (
                key == "video"
                and isinstance(item, dict)
                and _looks_like_video_asset(item)
                and not include_video
            ):
                continue
            child = _filter_language_node(
                item,
                allowed_languages,
                include_video=include_video,
            )
            if child is not _DROP:
                filtered[key] = child
        return filtered
    if isinstance(value, list):
        filtered_items: list[Any] = []
        for item in value:
            if (
                isinstance(item, str)
                and item in SUPPORTED_LANGUAGES
                and item not in allowed_languages
            ):
                continue
            child = _filter_language_node(
                item,
                allowed_languages,
                include_video=include_video,
            )
            if child is not _DROP:
                filtered_items.append(child)
        return filtered_items
    return copy.deepcopy(value)


def _declares_disallowed_language(
    value: dict[str, Any], allowed_languages: set[str]
) -> bool:
    for key, declared in value.items():
        if not _is_language_declaration_key(key) or not isinstance(declared, str):
            continue
        if declared in SUPPORTED_LANGUAGES and declared not in allowed_languages:
            return True
    return False


def _is_language_declaration_key(key: str) -> bool:
    return (
        key in LANGUAGE_DECLARATION_KEYS
        or key in {"lang", "locale"}
        or key.endswith("_language")
        or key.endswith("_locale")
    )


def _references_disallowed_language(
    value: dict[str, Any], allowed_languages: set[str]
) -> bool:
    for key, reference in value.items():
        if not isinstance(reference, str) or not _is_path_reference_key(key):
            continue
        if _language_tokens(reference) - allowed_languages:
            return True
    return False


def _is_path_reference_key(key: str) -> bool:
    return key in PATH_REFERENCE_KEYS or key.endswith("_path")


def _language_tokens(value: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"(?<![A-Za-z0-9])(zh|en|ja)(?![A-Za-z0-9])", value)
    }


def _looks_like_video_asset(value: dict[str, Any]) -> bool:
    return bool(VIDEO_ASSET_KEYS & value.keys())


def _references_video_asset(value: dict[str, Any]) -> bool:
    if _looks_like_video_asset(value):
        return True
    for key, reference in value.items():
        if not isinstance(reference, str) or not _is_path_reference_key(key):
            continue
        normalized = reference.lower().replace("[", ".").replace("]", ".")
        if re.search(r"(?:^|[./_\-])video(?:$|[./_\-])", normalized):
            return True
    return False


def _requested_languages(campaign: CampaignDetail) -> list[str]:
    requested: list[str] = []
    for language in campaign.languages:
        if language in SUPPORTED_LANGUAGES and language not in requested:
            requested.append(language)
    if not requested:
        raise HTTPException(status_code=422, detail="Campaign has no supported export language")
    return requested


def _annotate_video_export(
    manifest: dict[str, Any],
    *,
    language: str | None,
    video_included: bool,
    narration_language: Any,
) -> None:
    if language is None:
        manifest["shared_assets"] = {
            **(
                manifest.get("shared_assets", {})
                if isinstance(manifest.get("shared_assets"), dict)
                else {}
            ),
            "video": {
                "included": video_included,
                "scope": "shared",
                "archive_path": "shared/video.mp4" if video_included else None,
                "narration_language": (
                    narration_language if narration_language in SUPPORTED_LANGUAGES else None
                ),
                "single_language_exports_require_matching_narration": True,
            },
        }
        return
    manifest["language_assets"] = {
        **(
            manifest.get("language_assets", {})
            if isinstance(manifest.get("language_assets"), dict)
            else {}
        ),
        "video": (
            {
                "included": True,
                "scope": "language",
                "archive_path": f"{language}/video.mp4",
                "narration_language": language,
            }
            if video_included
            else {
                "included": False,
                "scope": "language",
                "reason": "no_verified_matching_narration",
            }
        ),
    }


def _read_existing_json(value: Any, package_dir: Path) -> Any:
    path = _optional_artifact_file(value, package_dir)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_exact_campaign_file(value: Any, uploads_dir: Path) -> Path:
    path = _optional_exact_campaign_file(value, uploads_dir)
    if path is None:
        raise HTTPException(status_code=404, detail="Campaign asset not found")
    return path


def _optional_exact_campaign_file(value: Any, uploads_dir: Path) -> Path | None:
    if not isinstance(value, str):
        return None
    try:
        resolved = Path(value).resolve(strict=True)
        resolved.relative_to(uploads_dir.resolve())
    except (FileNotFoundError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def _resolve_artifact_file(value: Any, package_dir: Path) -> Path:
    path = _optional_artifact_file(value, package_dir)
    if path is None:
        raise HTTPException(status_code=404, detail="Campaign asset not found")
    return path


def _optional_artifact_file(value: Any, package_dir: Path) -> Path | None:
    if not isinstance(value, str):
        return None
    try:
        resolved = Path(value).resolve(strict=True)
        resolved.relative_to(package_dir.resolve())
    except (FileNotFoundError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def _write_json(archive: zipfile.ZipFile, name: str, value: Any) -> None:
    _assert_safe_archive_name(name)
    archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2))


def _write_file(archive: zipfile.ZipFile, path: Path, name: str) -> None:
    _assert_safe_archive_name(name)
    archive.write(path, name)


def _assert_safe_archive_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise ValueError(f"unsafe ZIP member name: {name}")
    if any(part in {".", ".."} for part in path.parts):
        raise ValueError(f"unsafe ZIP member name: {name}")


def _filename_slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    return "-".join(part for part in slug.split("-") if part)[:80] or "campaign"
