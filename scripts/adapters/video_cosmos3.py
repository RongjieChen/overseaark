#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from adapter_common import cuda_cleanup, models_root, read_payload, require_path, write_result


def main() -> None:
    payload = read_payload()
    checkpoint = require_path(models_root() / "nvidia/cosmos3-edge", "Cosmos3-Edge checkpoint")
    output_path = Path(payload["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="overseaark-cosmos3-") as tmp:
        input_json = Path(tmp) / "input.json"
        output_dir = Path(tmp) / "out"
        input_json.write_text(
            json.dumps(
                {
                    "model_mode": "image2video",
                    "prompt": payload["prompt"],
                    "vision_path": str(payload["image_path"]),
                    "resolution": 480,
                    "aspect_ratio": "16,9",
                    "fps": 24,
                    "num_frames": 121,
                    "num_steps": 35,
                    "guidance": 6.0,
                    "shift": 5.0,
                    "seed": 0,
                }
            ),
            encoding="utf-8",
        )
        cmd = [
            sys.executable,
            "-m",
            "cosmos_framework.scripts.inference",
            "-i",
            str(input_json),
            "-o",
            str(output_dir),
            "--checkpoint-path",
            str(checkpoint),
            "--parallelism-preset=latency",
            "--sampler=unipc",
            "--no-guardrails",
        ]
        env = os.environ.copy()
        env.update(
            {
                "COSMOS_TRAINING": "0",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            }
        )
        subprocess.run(cmd, check=True, env=env)
        produced_files = sorted(output_dir.rglob("*.mp4"))
        if not produced_files:
            raise SystemExit(f"Cosmos3 produced no MP4 under {output_dir}")
        produced = produced_files[0]
        shutil.copyfile(produced, output_path)
    write_result({"video_path": str(output_path), "model": str(checkpoint)})


if __name__ == "__main__":
    try:
        main()
    finally:
        cuda_cleanup()
