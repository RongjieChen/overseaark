#!/usr/bin/env python3
from __future__ import annotations

import re
import sys

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, run_resident, write_result

LANGUAGE_PROMPTS = {
    "auto": "auto",
    "zh": "zh-CN",
    "en": "en-US",
    "ja": "ja-JP",
}


def _value(item: object, name: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _segments(result: object, text: str) -> list[dict[str, object]]:
    timestamp = _value(result, "timestamp", {})
    if not isinstance(timestamp, dict):
        return [{"start": 0.0, "end": 0.0, "text": text}]
    words = timestamp.get("word") or timestamp.get("segment") or []
    segments = []
    for item in words:
        if not isinstance(item, dict):
            continue
        segment_text = str(item.get("word") or item.get("segment") or item.get("text") or "")
        if re.fullmatch(r"<[a-z]{2}(?:-[A-Z]{2})?>", segment_text):
            continue
        segments.append(
            {
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "text": segment_text,
            }
        )
    return segments or [{"start": 0.0, "end": 0.0, "text": text}]


def build_worker():
    model_path = require_path(
        models_root() / "nvidia/nemotron-3.5-asr-streaming-0.6b/nemotron-3.5-asr-streaming-0.6b.nemo",
        "Nemotron ASR .nemo",
    )
    try:
        import nemo.collections.asr as nemo_asr
        from nemo.collections.asr.models.rnnt_bpe_models_prompt import RNNTPromptTranscribeConfig
    except Exception as exc:
        raise SystemExit("ASR adapter requires NVIDIA NeMo installed in the ASR environment") from exc

    model = nemo_asr.models.ASRModel.restore_from(str(model_path), map_location="cuda")

    def transcribe(payload: dict[str, object]) -> dict[str, object]:
        language = str(payload.get("language") or "auto")
        if language not in LANGUAGE_PROMPTS:
            raise SystemExit(f"unsupported ASR language: {language}")
        transcribe_config = RNNTPromptTranscribeConfig(
            use_lhotse=False,
            batch_size=1,
            return_hypotheses=True,
            num_workers=0,
            timestamps=True,
            target_lang=LANGUAGE_PROMPTS[language],
        )
        result = model.transcribe(
            [payload["audio_path"]],
            timestamps=True,
            override_config=transcribe_config,
        )[0]
        text = str(_value(result, "text", result if isinstance(result, str) else ""))
        tag = re.search(r"<([a-z]{2}(?:-[A-Z]{2})?)>\s*$", text)
        tagged_language = tag.group(1) if tag else None
        if tag:
            text = text[: tag.start()].rstrip()
        detected = str(
            _value(result, "language", _value(result, "lang", tagged_language or language))
        )
        if detected in LANGUAGE_PROMPTS.values():
            detected = detected.split("-", 1)[0]
        return {
            "text": text,
            "language": detected,
            "detected_language": detected,
            "segments": _segments(result, text),
            "model": str(model_path),
        }

    return transcribe


def main() -> None:
    write_result(build_worker()(read_payload()))


if __name__ == "__main__":
    try:
        if "--resident" in sys.argv[1:]:
            run_resident(build_worker)
        else:
            main()
    finally:
        cuda_cleanup()
