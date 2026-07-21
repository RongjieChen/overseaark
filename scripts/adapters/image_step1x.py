#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, write_result


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _overlay_headline(image: Image.Image, text: str) -> Image.Image:
    if not text.strip():
        return image
    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = _font(max(26, canvas.width // 24))
    margin = max(24, canvas.width // 30)
    max_width = canvas.width - margin * 2
    words = list(text) if " " not in text else text.split()
    joiner = "" if " " not in text else " "
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current}{joiner if current else ''}{word}"
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    line_height = int(font.size * 1.35) if hasattr(font, "size") else 32
    box_height = line_height * len(lines) + margin * 2
    top = canvas.height - box_height
    draw.rounded_rectangle(
        (margin // 2, top, canvas.width - margin // 2, canvas.height - margin // 2),
        radius=max(16, margin // 2),
        fill=(8, 18, 40, 210),
    )
    for index, line in enumerate(lines):
        draw.text((margin, top + margin + index * line_height), line, font=font, fill=(255, 255, 255, 255))
    return canvas.convert("RGB")


def main() -> None:
    payload = read_payload()
    model_dir = require_path(models_root() / "stepfun/step1x-edit-v1p2", "Step1X-Edit-v1p2 model")
    output_path = Path(payload["output_path"])

    try:
        import torch
        from diffusers import Step1XEditPipelineV1P2
    except Exception as exc:
        raise SystemExit(
            "Step1X adapter requires transformers==4.55.0 and Peyton-Chen/diffusers "
            "branch step1xedit_v1p2"
        ) from exc

    pipe = Step1XEditPipelineV1P2.from_pretrained(model_dir, torch_dtype=torch.bfloat16)
    fp8_layerwise = False
    transformer = getattr(pipe, "transformer", None)
    if transformer is not None and hasattr(transformer, "enable_layerwise_casting"):
        transformer.enable_layerwise_casting(
            storage_dtype=torch.float8_e4m3fn,
            compute_dtype=torch.bfloat16,
            skip_modules_pattern=("pos_embed", "norm", "connector"),
        )
        fp8_layerwise = True
    cpu_offload = os.environ.get("OVERSEAARK_STEP1X_CPU_OFFLOAD", "0") == "1"
    if cpu_offload and hasattr(pipe, "enable_model_cpu_offload"):
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    source = Image.open(payload["source_image"]).convert("RGB")
    generator = torch.Generator(device="cpu").manual_seed(int(payload.get("seed", 0)))
    num_inference_steps = int(
        payload.get("num_inference_steps", os.environ.get("OVERSEAARK_STEP1X_STEPS", "8"))
    )
    thinking = bool(
        payload.get(
            "enable_thinking_mode",
            os.environ.get("OVERSEAARK_STEP1X_THINKING", "0") == "1",
        )
    )
    reflection = bool(
        payload.get(
            "enable_reflection_mode",
            os.environ.get("OVERSEAARK_STEP1X_REFLECTION", "0") == "1",
        )
    )
    generation_prompt = (
        f"{str(payload['prompt']).rstrip()} Preserve the product geometry and use a clean studio background. "
        "Do not render text, letters, logos, captions, or watermarks; typography is added after generation."
    )
    pipe_output = pipe(
        prompt=generation_prompt,
        image=source,
        num_inference_steps=num_inference_steps,
        true_cfg_scale=float(payload.get("true_cfg_scale", 6.0)),
        generator=generator,
        enable_thinking_mode=thinking,
        enable_reflection_mode=reflection,
    )
    image = _overlay_headline(pipe_output.final_images[0], str(payload.get("overlay_text", "")))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    write_result(
        {
            "image_path": str(output_path),
            "model": str(model_dir),
            "fp8_layerwise": fp8_layerwise,
            "cpu_offload": cpu_offload,
            "num_inference_steps": num_inference_steps,
            "thinking": thinking,
            "reflection": reflection,
        }
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        cuda_cleanup()
