#!/usr/bin/env python3
"""Run direct local model benchmarks using the same command-adapter contract as FastAPI."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TEXTS = {
    "zh": "这是一款轻巧可靠的旅行充电器，让跨境出行更简单。",
    "en": "A compact and reliable travel charger makes every journey easier.",
    "ja": "小型で信頼できる旅行用充電器が、海外出張をもっと快適にします。",
}
VOICES = {
    "zh": ("Sofia", "Jason"),
    "en": ("Jason", "Sofia"),
    "ja": ("Aria", "Leo"),
}


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def run_adapter(
    command_env: str,
    payload: dict[str, Any],
    *,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    command = os.environ.get(command_env)
    if not command:
        raise RuntimeError(f"missing {command_env}")
    started = time.perf_counter()
    timeout = int(os.environ.get("OVERSEAARK_BENCH_TIMEOUT", "1200"))
    process = subprocess.Popen(
        shlex.split(command),
        stdin=subprocess.PIPE,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, **(extra_env or {})},
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            json.dumps(payload, ensure_ascii=False), timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise RuntimeError(
            f"{command_env} timed out after {timeout}s; its process group was terminated"
        ) from exc
    if process.returncode != 0:
        raise RuntimeError(stderr.strip() or f"{command_env} failed")
    result = json.loads(stdout)
    if not isinstance(result, dict):
        raise RuntimeError(f"{command_env} returned non-object JSON")
    result["wall_seconds"] = round(time.perf_counter() - started, 3)
    return result


def similarity(reference: str, candidate: str) -> float:
    def normalize(value: str) -> str:
        return "".join(re.findall(r"[\w]+", value.lower(), flags=re.UNICODE))

    return difflib.SequenceMatcher(None, normalize(reference), normalize(candidate)).ratio()


def write_product_image(path: Path) -> None:
    width = height = 512
    header = f"P6\n{width} {height}\n255\n".encode()
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.extend((24 + x * 80 // width, 64 + y * 96 // height, 160))
    path.write_bytes(header + pixels)


def image_benchmark(workdir: Path) -> dict[str, Any]:
    source = workdir / "product.ppm"
    output = workdir / "poster.png"
    write_product_image(source)
    return run_adapter(
        "OVERSEAARK_IMAGE_COMMAND",
        {
            "prompt": "Turn this product into a premium cross-border ecommerce studio poster.",
            "overlay_text": "Ready for every journey",
            "source_image": str(source),
            "output_path": str(output),
            "seed": 0,
        },
    )


def audio_benchmark(workdir: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for cycle in range(1, 4):
        for language, text in TEXTS.items():
            for speaker in VOICES[language]:
                stem = f"cycle{cycle}-{language}-{speaker.lower()}"
                wav = workdir / f"{stem}.wav"
                tts = run_adapter(
                    "OVERSEAARK_TTS_COMMAND",
                    {
                        "text": text,
                        "language": language,
                        "speaker": speaker,
                        "output_path": str(wav),
                    },
                )
                checks = []
                for requested_language in (language, "auto"):
                    asr = run_adapter(
                        "OVERSEAARK_ASR_COMMAND",
                        {"audio_path": str(wav), "language": requested_language},
                    )
                    score = similarity(text, str(asr.get("text", "")))
                    detected = str(asr.get("detected_language", asr.get("language", ""))).lower()
                    checks.append(
                        {
                            "requested_language": requested_language,
                            "detected_language": detected,
                            "text": asr.get("text"),
                            "similarity": score,
                            "wall_seconds": asr["wall_seconds"],
                        }
                    )
                    if score < 0.75:
                        failures.append(f"{stem}/{requested_language} similarity={score:.3f}")
                    if requested_language == "auto" and not detected.startswith(language):
                        failures.append(
                            f"{stem}/auto detected_language={detected!r}, expected {language!r}"
                        )
                results.append(
                    {
                        "cycle": cycle,
                        "language": language,
                        "speaker": speaker,
                        "wav": str(wav),
                        "tts_duration": tts.get("duration"),
                        "tts_wall_seconds": tts["wall_seconds"],
                        "checks": checks,
                    }
                )
    return {"runs": results, "failures": failures, "passed": not failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("modality", choices=("llm", "image", "audio", "video"))
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    workdir = args.output_root / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{args.modality}"
    workdir.mkdir(parents=True, exist_ok=False)

    if args.modality == "llm":
        product = workdir / "product.ppm"
        write_product_image(product)
        llm_env = (
            {}
            if "OVERSEAARK_LLM_TOKENS" in os.environ
            else {"OVERSEAARK_LLM_TOKENS": "192"}
        )
        result = run_adapter(
            "OVERSEAARK_LLM_COMMAND",
            {
                "task": "market_positioning",
                "description": "A compact travel charger for cross-border buyers.",
                "source_market": "CN",
                "target_markets": ["US", "JP"],
                "languages": ["zh", "en", "ja"],
                "product_image_path": str(product),
            },
            extra_env=llm_env,
        )
    elif args.modality == "image":
        result = image_benchmark(workdir)
    elif args.modality == "video":
        image = image_benchmark(workdir)
        result = {
            "image": image,
            "video": run_adapter(
                "OVERSEAARK_VIDEO_COMMAND",
                {
                    "prompt": "A smooth premium 480p product reveal for a travel charger.",
                    "image_path": image["image_path"],
                    "output_path": str(workdir / "cosmos-video.mp4"),
                },
            ),
        }
    else:
        result = audio_benchmark(workdir)

    report = {
        "modality": args.modality,
        "created_at": datetime.now(UTC).isoformat(),
        "offline": os.environ.get("HF_HUB_OFFLINE") == "1"
        and os.environ.get("TRANSFORMERS_OFFLINE") == "1",
        "result": result,
    }
    report_path = workdir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)
    if args.modality == "audio" and not result["passed"]:
        print("\n".join(result["failures"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
