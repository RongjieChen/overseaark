#!/usr/bin/env python3
from __future__ import annotations

import base64
import copy
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from adapter_common import models_root, read_payload, require_path, write_result


MODEL_ID = "nvidia/Qwen3.6-35B-A3B-NVFP4"
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
TASK_TOKEN_LIMITS = {
    "market_positioning": 768,
    "buyer_persona": 1024,
    "multilingual_copy": 3072,
    "quality_packaging": 768,
}


def _schema_for_task(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    schema = copy.deepcopy(
        TASK_SCHEMAS.get(
            task,
            {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        )
    )
    if task == "multilingual_copy":
        languages = list(dict.fromkeys(payload.get("languages") or ["zh", "en", "ja"]))
        copy_schema = schema["properties"]["copy"]
        localized_schema = copy_schema.pop("additionalProperties")
        copy_schema.update(
            {
                "properties": {language: copy.deepcopy(localized_schema) for language in languages},
                "required": languages,
                "additionalProperties": False,
            }
        )
    return schema


def _task_token_limit(task: str) -> int:
    configured = os.environ.get("OVERSEAARK_LLM_TOKENS")
    return int(configured) if configured else TASK_TOKEN_LIMITS.get(task, 768)


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


def _image_data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _messages(payload: dict[str, Any], task: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    image_path = payload.get("product_image_path")
    prompt_payload = dict(payload)
    prompt_payload.pop("product_image_path", None)
    prompt = (
        "You are OverseaArk's local cross-border marketing planner. "
        "Return only the requested JSON object; do not include Markdown or reasoning.\n"
        f"Task: {task}\n"
        f"Required output languages: {json.dumps(payload.get('languages', []), ensure_ascii=False)}\n"
        f"Output JSON Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        f"Input JSON: {json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    if task == "multilingual_copy":
        prompt += (
            "\nUse exactly the requested language keys and localize every field, including "
            "title, headline, selling_points, detail, body, outreach_email, video_script, and CTA. "
            "The zh object must be natural Simplified Chinese, the en object must be idiomatic "
            "English, and the ja object must be natural Japanese containing Japanese script. "
            "Do not copy source-language sentences into a different language object; only unavoidable "
            "brand names, model names, units, and product codes may remain in their original script. "
            "Keep every field concise. "
            "Each video_script must be natural speech lasting about 5 seconds: "
            "at most 28 Chinese/Japanese characters or 16 English words. "
            "For a zh video_script, use only Chinese characters and punctuation; "
            "expand Latin abbreviations, units, and product codes into natural Chinese words. "
            "For a ja video_script, render Latin abbreviations as pronounceable Japanese script."
        )
    if not image_path:
        return [{"role": "user", "content": prompt}]
    image = require_path(Path(str(image_path)).resolve(), "campaign product image")
    return [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _image_data_url(image)}},
                {"type": "text", "text": prompt},
            ],
        }
    ]


def _local_vllm_endpoint() -> str:
    base_url = os.environ.get("OVERSEAARK_LLM_BASE_URL", "http://127.0.0.1:8011")
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit(f"refusing non-local vLLM endpoint: {base_url}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SystemExit(f"invalid local vLLM base URL: {base_url}")
    return f"{base_url.rstrip('/')}/v1/chat/completions"


def _invoke_vllm(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    key_file = os.environ.get("OVERSEAARK_VLLM_API_KEY_FILE")
    if key_file:
        key_path = Path(key_file)
        if not key_path.is_file():
            raise SystemExit(f"local vLLM API key file is missing: {key_file}")
        key = key_path.read_text(encoding="utf-8").strip()
        if not key:
            raise SystemExit(f"local vLLM API key file is empty: {key_file}")
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        _local_vllm_endpoint(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=int(os.environ.get("OVERSEAARK_LLM_TIMEOUT", "600")),
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"local vLLM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"local vLLM request failed: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise SystemExit("local vLLM returned a non-object response")
    return result


def main() -> None:
    payload = read_payload()
    task = str(payload.pop("task", "general"))
    schema = _schema_for_task(task, payload)
    require_path(
        models_root() / "nvidia/qwen3.6-35b-a3b-nvfp4/config.json",
        "NVIDIA Qwen3.6-35B-A3B NVFP4",
    )
    request = {
        "model": MODEL_ID,
        "messages": _messages(payload, task, schema),
        "max_tokens": _task_token_limit(task),
        "temperature": 0.2,
        "top_p": 0.95,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": task, "strict": True, "schema": schema},
        },
    }
    response = _invoke_vllm(request)
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit(f"local vLLM response is missing assistant content: {response}") from exc
    if not isinstance(content, str):
        raise SystemExit("local vLLM assistant content is not text")
    try:
        result = _extract_task_result(content, task)
    except SystemExit as exc:
        finish_reason = response.get("choices", [{}])[0].get("finish_reason", "unknown")
        raise SystemExit(
            f"{exc}; finish_reason={finish_reason}; content_characters={len(content)}"
        ) from exc
    result.setdefault("model", MODEL_ID)
    write_result(result)


if __name__ == "__main__":
    main()
