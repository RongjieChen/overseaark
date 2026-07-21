#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, write_result


TASK_SCHEMAS = {
    "market_positioning": '{"positioning": string, "differentiators": string[], "market_hypotheses": string[]}',
    "buyer_persona": '{"personas": [{"name": string, "pain_points": string[], "purchase_motivations": string[], "channel_recommendations": string[], "needs": string[]}]}',
    "multilingual_copy": '{"copy": {"<language>": {"title": string, "headline": string, "selling_points": string[], "detail": string, "body": string, "outreach_email": string, "video_script": string, "cta": string}}}',
    "quality_packaging": '{"qc": {"passed": boolean, "checks": string[]}}',
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
    default_schema = '{"text": string}'
    prompt = (
        "You are OverseaArk's local offline planning model. Return only valid JSON.\n"
        f"Task: {task}\n"
        f"Expected schema: {TASK_SCHEMAS.get(task, default_schema)}\n"
        f"Input JSON: {json.dumps(payload, ensure_ascii=False)}\n"
    )
    cmd = [
        llama_cli,
        "-m",
        str(shard),
        "-p",
        prompt,
        "-n",
        os.environ.get("OVERSEAARK_LLM_TOKENS", "1024"),
        "--temp",
        "0.2",
        "--no-display-prompt",
    ]
    image_path = payload.get("product_image_path")
    if image_path:
        image = require_path(Path(str(image_path)), "campaign product image")
        mmproj = require_path(model_dir / "mmproj-step3.7-flash-f16.gguf", "Step-3.7 mmproj")
        cmd.extend(["--mmproj", str(mmproj), "--image", str(image)])
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
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
