#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, run_resident, write_result


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


def _enable_japanese_inference(model: object) -> None:
    """Bridge NeMo 2.7's do_tts helper to the Japanese tokenizer in v2602."""
    tokenizers = model.tokenizer.tokenizers
    japanese = tokenizers.get("japanese_phoneme")
    if japanese is None:
        raise SystemExit("Magpie checkpoint does not contain its Japanese tokenizer")
    model.tokenizer.tokenizers = {
        "japanese_phoneme": japanese,
        **{name: tokenizer for name, tokenizer in tokenizers.items() if name != "japanese_phoneme"},
    }
    original_longform_check = model._needs_longform_inference
    model._needs_longform_inference = (
        lambda text, language: False
        if language == "ja"
        else original_longform_check(text, language)
    )


def build_worker():
    model_path = require_path(
        models_root() / "nvidia/magpie_tts_multilingual_357m/magpie_tts_multilingual_357m.nemo",
        "Magpie TTS .nemo",
    )
    codec_path = require_path(
        models_root()
        / "nvidia/nemo-nano-codec-22khz-1.89kbps-21.5fps/nemo-nano-codec-22khz-1.89kbps-21.5fps.nemo",
        "Magpie NanoCodec .nemo",
    )
    tokenizer_path = require_path(
        models_root() / "google/byt5-small",
        "Magpie ByT5 tokenizer",
    )

    try:
        import soundfile as sf
        from nemo.collections.tts.models import AudioCodecModel, MagpieTTSModel
    except Exception as exc:
        raise SystemExit("TTS adapter requires NVIDIA NeMo and soundfile installed in the TTS environment") from exc

    config = MagpieTTSModel.restore_from(str(model_path), return_config=True)
    config.codecmodel_path = str(codec_path)
    for tokenizer_config in config.text_tokenizers.values():
        if tokenizer_config.get("_target_") == "AutoTokenizer":
            tokenizer_config.pretrained_model = str(tokenizer_path)
    original_codec_restore = AudioCodecModel.restore_from

    def restore_inference_codec(restore_path: str, *args: object, **kwargs: object) -> object:
        """Prevent NeMo from constructing training-only codec discriminators."""
        if kwargs.get("return_config"):
            return original_codec_restore(restore_path, *args, **kwargs)
        codec_config = kwargs.get("override_config_path")
        if codec_config is None:
            codec_config = original_codec_restore(restore_path, return_config=True)
        codec_config.discriminator = None
        if "use_scl_loss" in codec_config:
            codec_config.use_scl_loss = False
        kwargs["override_config_path"] = codec_config
        kwargs["strict"] = False
        return original_codec_restore(restore_path, *args, **kwargs)

    AudioCodecModel.restore_from = restore_inference_codec
    try:
        model = MagpieTTSModel.restore_from(
            str(model_path),
            override_config_path=config,
            map_location="cuda",
        )
    finally:
        AudioCodecModel.restore_from = original_codec_restore
    import numpy as np

    japanese_enabled = False

    def synthesize(payload: dict[str, object]) -> dict[str, object]:
        nonlocal japanese_enabled
        output_path = Path(str(payload["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        speaker = str(payload.get("speaker", "Sofia"))
        language = str(payload.get("language", "en"))
        if language == "ja":
            import pyopenjtalk

            require_path(
                Path(pyopenjtalk.OPEN_JTALK_DICT_DIR.decode()),
                "Open JTalk dictionary (run ./overseaark bootstrap while online)",
            )
            if not japanese_enabled:
                _enable_japanese_inference(model)
                japanese_enabled = True
        sample_rate = int(getattr(model, "sample_rate", 22050))
        text = str(payload["text"])
        pending = _split_text(text, language)
        generated = []
        while pending:
            chunk = pending.pop(0)
            audio, audio_len = model.do_tts(
                chunk,
                language=language,
                apply_TN=payload.get("apply_TN", False),
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
        return {
            "audio_path": str(output_path),
            "language": language,
            "speaker": speaker,
            "duration": round(len(merged) / sample_rate, 3),
            "segments": len(generated),
            "text": text,
            "model": str(model_path),
        }

    return synthesize


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
