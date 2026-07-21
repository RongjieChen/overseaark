#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, write_result


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


def main() -> None:
    payload = read_payload()
    model_dir = models_root() / "stepfun/step-3.7-flash"
    shard = require_path(
        model_dir / "Q3_K_M/Step-3.7-flash-Q3_K_M-00001-of-00003.gguf",
        "Step-3.7 Flash Q3_K_M shard 1",
    )
    llama_cli = os.environ.get("OVERSEAARK_LLAMA_CLI", "/root/llama.cpp/build/bin/llama-cli")
    require_path(__import__("pathlib").Path(llama_cli), "llama-cli")

    task = payload.pop("task", "general")
    default_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    schema = TASK_SCHEMAS.get(task, default_schema)
    prompt = (
        "You are OverseaArk's local offline planning model. Return only valid JSON.\n"
        f"Task: {task}\n"
        "Required output languages: "
        f"{json.dumps(payload.get('languages', []), ensure_ascii=False)}\n"
        f"Input JSON: {json.dumps(payload, ensure_ascii=False)}\n"
    )
    cmd = [
        llama_cli,
        "-m",
        str(shard),
        "-p",
        prompt,
        "-n",
        os.environ.get("OVERSEAARK_LLM_TOKENS", "512"),
        "--ctx-size",
        os.environ.get("OVERSEAARK_LLM_CONTEXT", "2048"),
        "--batch-size",
        os.environ.get("OVERSEAARK_LLM_BATCH", "256"),
        "--ubatch-size",
        os.environ.get("OVERSEAARK_LLM_UBATCH", "128"),
        "--gpu-layers",
        "all",
        "--flash-attn",
        "on",
        "--json-schema",
        json.dumps(schema),
        "--temp",
        "0.2",
        "--no-display-prompt",
    ]
    image_path = payload.get("product_image_path")
    if image_path:
        image = require_path(Path(str(image_path)), "campaign product image")
        mmproj = require_path(model_dir / "mmproj-step3.7-flash-f16.gguf", "Step-3.7 mmproj")
        cmd.extend(["--mmproj", str(mmproj), "--image", str(image)])
    proc = subprocess.run(
        cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "llama-cli failed")
    text = proc.stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise SystemExit("llama-cli did not return a JSON object")
    result = json.loads(text[start : end + 1])
    result.setdefault("model", "stepfun-ai/Step-3.7-Flash-GGUF")
    write_result(result)


if __name__ == "__main__":
    try:
        main()
    finally:
        cuda_cleanup()
