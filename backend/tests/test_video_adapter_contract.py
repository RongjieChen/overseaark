from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_DIR = REPO_ROOT / "scripts" / "adapters"


def load_adapter():
    sys.path.insert(0, str(ADAPTER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "overseaark_video_cosmos3", ADAPTER_DIR / "video_cosmos3.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ADAPTER_DIR))


def test_cosmos_adapter_uses_offline_inference_mode_and_json_sample_overrides(
    monkeypatch, tmp_path: Path
):
    adapter = load_adapter()
    checkpoint = tmp_path / "models" / "nvidia" / "cosmos3-edge"
    checkpoint.mkdir(parents=True)
    source_image = tmp_path / "source.png"
    source_image.write_bytes(b"png")
    target_video = tmp_path / "campaign.mp4"
    captured: dict[str, object] = {}

    monkeypatch.setattr(adapter, "models_root", lambda: tmp_path / "models")
    monkeypatch.setattr(
        adapter,
        "read_payload",
        lambda: {
            "prompt": "A product rotates slowly on a studio pedestal.",
            "image_path": str(source_image),
            "output_path": str(target_video),
        },
    )
    monkeypatch.setattr(adapter, "write_result", lambda value: captured.update(result=value))

    def fake_run(cmd, *, check, env):
        assert check is True
        captured["cmd"] = cmd
        captured["env"] = env
        input_path = Path(cmd[cmd.index("-i") + 1])
        captured["sample"] = json.loads(input_path.read_text(encoding="utf-8"))
        output_dir = Path(cmd[cmd.index("-o") + 1])
        output_dir.mkdir(parents=True)
        (output_dir / "vision.mp4").write_bytes(b"video")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    adapter.main()

    assert target_video.read_bytes() == b"video"
    assert captured["env"]["COSMOS_TRAINING"] == "0"
    assert captured["env"]["HF_HUB_OFFLINE"] == "1"
    assert captured["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert "--no-guardrails" in captured["cmd"]
    assert not any(str(arg).startswith("--num-steps") for arg in captured["cmd"])
    assert captured["sample"] == {
        "model_mode": "image2video",
        "prompt": "A product rotates slowly on a studio pedestal.",
        "vision_path": str(source_image),
        "resolution": "480",
        "aspect_ratio": "16,9",
        "fps": 24,
        "num_frames": 121,
        "num_steps": 35,
        "guidance": 6.0,
        "shift": 5.0,
        "seed": 0,
    }
