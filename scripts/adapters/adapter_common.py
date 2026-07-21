#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def models_root() -> Path:
    return Path(os.environ.get("OVERSEAARK_MODELS_DIR") or os.environ.get("OVERSEAARK_MODEL_ROOT", "overseaark-models"))


def read_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid stdin JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("stdin JSON must be an object")
    return payload


def write_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False))


def require_path(path: Path, label: str) -> Path:
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    return path


def cuda_cleanup() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        return
