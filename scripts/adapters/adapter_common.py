#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable


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


def _resident_error(exc: Exception | SystemExit) -> dict[str, Any]:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = f"{exc.__class__.__name__}: {message}".lower()
    fatal = isinstance(exc, RuntimeError) or any(
        marker in lowered
        for marker in (
            "cuda",
            "cudnn",
            "cublas",
            "out of memory",
            "oom",
        )
    )
    return {
        "type": exc.__class__.__name__,
        "message": message,
        "fatal": fatal,
        "restart_worker": fatal,
    }


def run_resident(worker_factory: Callable[[], Callable[[dict[str, Any]], dict[str, Any]]]) -> None:
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1, encoding="utf-8")
    handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    with redirect_stdout(sys.stderr):
        for line in sys.stdin:
            request_id = ""
            restart_worker = False
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("resident request must be a JSON object")
                request_id = str(message.get("request_id") or "")
                if not request_id:
                    raise ValueError("resident request missing request_id")
                action = str(message.get("action") or "request")
                if handler is None:
                    handler = worker_factory()
                if action == "warmup":
                    result = {"ready": True}
                elif action == "request":
                    payload = message.get("payload")
                    if not isinstance(payload, dict):
                        raise ValueError("resident request payload must be an object")
                    result = handler(payload)
                else:
                    raise ValueError(f"unsupported resident action: {action}")
                response = {"request_id": request_id, "ok": True, "result": result}
            except (Exception, SystemExit) as exc:  # noqa: BLE001 - protocol boundary.
                error = _resident_error(exc)
                restart_worker = bool(error["restart_worker"])
                response = {"request_id": request_id, "ok": False, "error": error}
            protocol.write(json.dumps(response, ensure_ascii=False) + "\n")
            protocol.flush()
            if restart_worker:
                # A CUDA/runtime failure can leave allocator and stream state
                # unusable. Exit only after the structured response is flushed;
                # the parent will replace this process before accepting work.
                break


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
