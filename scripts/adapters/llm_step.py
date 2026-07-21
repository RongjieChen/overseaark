#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, write_result


MODEL_ID = "stepfun-ai/Step3-VL-10B-FP8"
STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
TASK_SCHEMAS = {
    "market_positioning": {
        "type": "object",
        "properties": {
            "positioning": {"type": "string"},
            "differentiators": STRING_ARRAY,
            "market_hypotheses": STRING_ARRAY,
        },
        "required": ["positioning", "differentiators", "market_hypotheses"],
        "additionalProperties": False,
    },
    "buyer_persona": {
        "type": "object",
        "properties": {
            "personas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "pain_points": STRING_ARRAY,
                        "purchase_motivations": STRING_ARRAY,
                        "channel_recommendations": STRING_ARRAY,
                        "needs": STRING_ARRAY,
                    },
                    "required": [
                        "name",
                        "pain_points",
                        "purchase_motivations",
                        "channel_recommendations",
                        "needs",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["personas"],
        "additionalProperties": False,
    },
    "multilingual_copy": {
        "type": "object",
        "properties": {
            "copy": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "headline": {"type": "string"},
                        "selling_points": STRING_ARRAY,
                        "detail": {"type": "string"},
                        "body": {"type": "string"},
                        "outreach_email": {"type": "string"},
                        "video_script": {"type": "string"},
                        "cta": {"type": "string"},
                    },
                    "required": [
                        "title",
                        "headline",
                        "selling_points",
                        "detail",
                        "body",
                        "outreach_email",
                        "video_script",
                        "cta",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["copy"],
        "additionalProperties": False,
    },
    "quality_packaging": {
        "type": "object",
        "properties": {
            "qc": {
                "type": "object",
                "properties": {"passed": {"type": "boolean"}, "checks": STRING_ARRAY},
                "required": ["passed", "checks"],
                "additionalProperties": False,
            }
        },
        "required": ["qc"],
        "additionalProperties": False,
    },
}


def _extract_task_result(text: str, task: str) -> dict[str, object]:
    required = set(TASK_SCHEMAS.get(task, {"required": ["text"]})["required"])
    decoder = json.JSONDecoder()
    candidates: list[dict[str, object]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in reversed(candidates):
        if required <= candidate.keys():
            return candidate
    raise SystemExit(
        f"{MODEL_ID} returned no JSON object matching {task!r} required keys: "
        f"{', '.join(sorted(required))}"
    )


def _load_runtime(model_dir: Path) -> tuple[Any, Any]:
    from transformers import AutoModelForCausalLM, AutoProcessor

    key_mapping = {
        "^vision_model": "model.vision_model",
        r"^model(?!\.(language_model|vision_model))": "model.language_model",
        "vit_large_projector": "model.vit_large_projector",
    }
    processor = AutoProcessor.from_pretrained(
        model_dir,
        trust_remote_code=True,
        local_files_only=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        trust_remote_code=True,
        local_files_only=True,
        device_map="auto",
        torch_dtype="auto",
        key_mapping=key_mapping,
    ).eval()
    return processor, model


def _build_messages(payload: dict[str, Any], task: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    image_path = payload.get("product_image_path")
    payload_for_prompt = dict(payload)
    payload_for_prompt.pop("product_image_path", None)
    prompt = (
        "You are OverseaArk's local offline cross-border marketing planner. "
        "Do not reveal chain-of-thought. Return one JSON object and no Markdown.\n"
        f"Task: {task}\n"
        "Required output languages: "
        f"{json.dumps(payload.get('languages', []), ensure_ascii=False)}\n"
        f"Output JSON Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        f"Input JSON: {json.dumps(payload_for_prompt, ensure_ascii=False)}"
    )
    content: list[dict[str, Any]] = []
    if image_path:
        image = require_path(Path(str(image_path)).resolve(), "campaign product image")
        content.append({"type": "image", "url": str(image)})
    content.append({"type": "text", "text": prompt})
    return [{"role": "user", "content": content}]


def main() -> None:
    import torch

    payload = read_payload()
    task = str(payload.pop("task", "general"))
    schema = TASK_SCHEMAS.get(
        task,
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )
    model_dir = require_path(
        models_root() / "stepfun/step3-vl-10b-fp8",
        "Step3-VL-10B-FP8 model directory",
    )
    processor, model = _load_runtime(model_dir)
    messages = _build_messages(payload, task, schema)
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=int(os.environ.get("OVERSEAARK_LLM_TOKENS", "512")),
            do_sample=False,
        )
    decoded = processor.decode(
        generated[0, inputs["input_ids"].shape[-1] :],
        skip_special_tokens=True,
    )
    result = _extract_task_result(decoded, task)
    result.setdefault("model", MODEL_ID)
    write_result(result)


if __name__ == "__main__":
    try:
        main()
    finally:
        cuda_cleanup()
