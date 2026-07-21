#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, write_result


SPEAKERS = {
    "John": 0,
    "Sofia": 1,
    "Aria": 2,
    "Jason": 3,
    "Leo": 4,
}

MAX_CHARS = {"zh": 60, "ja": 60, "en": 180}
MAX_SEGMENT_SECONDS = 20.0


def _split_text(text: str, language: str) -> list[str]:
    limit = MAX_CHARS.get(language, 120)
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?;\n])\s*", text) if part.strip()]
    chunks: list[str] = []
    for sentence in sentences or [text.strip()]:
        while len(sentence) > limit:
            boundary = sentence.rfind(" ", 0, limit + 1) if language == "en" else limit
            boundary = boundary if isinstance(boundary, int) and boundary > 0 else limit
            chunks.append(sentence[:boundary].strip())
            sentence = sentence[boundary:].strip()
        if sentence:
            if chunks and len(chunks[-1]) + len(sentence) + 1 <= limit:
                chunks[-1] = f"{chunks[-1]} {sentence}" if language == "en" else f"{chunks[-1]}{sentence}"
            else:
                chunks.append(sentence)
    return chunks


def _to_mono(audio: object, length: object) -> "object":
    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    values = np.asarray(audio).squeeze()
    size = int(length.item()) if hasattr(length, "item") else int(length or values.shape[-1])
    return values[:size]


def main() -> None:
    payload = read_payload()
    model_path = require_path(
        models_root() / "nvidia/magpie_tts_multilingual_357m/magpie_tts_multilingual_357m.nemo",
        "Magpie TTS .nemo",
    )
    codec_path = require_path(
        models_root()
        / "nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps/nemo-nano-codec-22khz-1.89kbps-21.5fps.nemo",
        "Magpie NanoCodec .nemo",
    )
    output_path = Path(payload["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    speaker = payload.get("speaker", "Sofia")

    try:
        import soundfile as sf
        from nemo.collections.tts.models import MagpieTTSModel
    except Exception as exc:
        raise SystemExit("TTS adapter requires NVIDIA NeMo and soundfile installed in the TTS environment") from exc

    config = MagpieTTSModel.restore_from(str(model_path), return_config=True)
    config.codecmodel_path = str(codec_path)
    model = MagpieTTSModel.restore_from(
        str(model_path),
        override_config_path=config,
        map_location="cuda",
    )
    import numpy as np

    language = str(payload.get("language", "en"))
    sample_rate = int(getattr(model, "sample_rate", 22050))
    pending = _split_text(payload["text"], language)
    generated = []
    while pending:
        chunk = pending.pop(0)
        audio, audio_len = model.do_tts(
            chunk,
            language=language,
            apply_TN=payload.get("apply_TN", True),
            speaker_index=SPEAKERS.get(speaker, 1),
        )
        values = _to_mono(audio, audio_len)
        duration = len(values) / sample_rate
        if duration > MAX_SEGMENT_SECONDS and len(chunk) > 1:
            midpoint = len(chunk) // 2
            if language == "en":
                split_at = chunk.rfind(" ", 0, midpoint + 1)
                midpoint = split_at if split_at > 0 else midpoint
            pending[:0] = [chunk[:midpoint].strip(), chunk[midpoint:].strip()]
            continue
        if duration > MAX_SEGMENT_SECONDS:
            raise SystemExit("Magpie produced a segment longer than 20 seconds")
        generated.append(values)

    silence = np.zeros(int(sample_rate * 0.15), dtype=np.float32)
    merged = np.concatenate([part for values in generated for part in (values, silence)])
    if generated:
        merged = merged[: -len(silence)]
    sf.write(output_path, merged, sample_rate)
    write_result({
        "audio_path": str(output_path),
        "language": language,
        "speaker": speaker,
        "duration": round(len(merged) / sample_rate, 3),
        "segments": len(generated),
        "text": payload["text"],
        "model": str(model_path),
    })


if __name__ == "__main__":
    try:
        main()
    finally:
        cuda_cleanup()
