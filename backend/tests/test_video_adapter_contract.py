from __future__ import annotations

import importlib.util
import json
import sys
import types
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


def load_local_wrapper():
    spec = importlib.util.spec_from_file_location(
        "overseaark_cosmos_local_inference", ADAPTER_DIR / "cosmos_local_inference.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cosmos_adapter_uses_offline_inference_mode_and_json_sample_overrides(
    monkeypatch, tmp_path: Path
):
    adapter = load_adapter()
    checkpoint = tmp_path / "models" / "nvidia" / "cosmos3-edge"
    checkpoint.mkdir(parents=True)
    vae_checkpoint = tmp_path / "models" / "wan" / "wan2.2-vae" / "Wan2.2_VAE.pth"
    vae_checkpoint.parent.mkdir(parents=True)
    vae_checkpoint.write_bytes(b"vae")
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
    assert captured["env"]["OVERSEAARK_COSMOS_LOCAL_CHECKPOINT"] == str(checkpoint)
    assert captured["env"]["OVERSEAARK_COSMOS_VAE_CHECKPOINT"] == str(vae_checkpoint)
    assert Path(captured["cmd"][1]).name == "cosmos_local_inference.py"
    assert captured["cmd"][captured["cmd"].index("--checkpoint-path") + 1] == "Cosmos3-Edge"
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
        "num_steps": 28,
        "guidance": 6.0,
        "shift": 5.0,
        "seed": 0,
    }


def test_cosmos_local_wrapper_fails_closed_for_other_repositories(monkeypatch, tmp_path: Path):
    wrapper = load_local_wrapper()
    checkpoint = tmp_path / "cosmos3-edge"
    checkpoint.mkdir()
    vae_checkpoint = tmp_path / "Wan2.2_VAE.pth"
    vae_checkpoint.write_bytes(b"vae")
    monkeypatch.setenv("OVERSEAARK_COSMOS_LOCAL_CHECKPOINT", str(checkpoint))
    monkeypatch.setenv("OVERSEAARK_COSMOS_VAE_CHECKPOINT", str(vae_checkpoint))

    class FakeCheckpointDirHf:
        def __init__(self, repository: str):
            self.repository = repository

    class FakeCheckpointFileHf:
        def __init__(self, repository: str, revision: str, filename: str):
            self.repository = repository
            self.revision = revision
            self.filename = filename

    checkpoint_module = types.ModuleType("cosmos_framework.utils.checkpoint_db")
    checkpoint_module.CheckpointDirHf = FakeCheckpointDirHf
    checkpoint_module.CheckpointFileHf = FakeCheckpointFileHf
    inference_module = types.ModuleType("cosmos_framework.scripts.inference")
    calls: list[str] = []

    def fake_cosmos_main():
        calls.append(FakeCheckpointDirHf("nvidia/Cosmos3-Edge")._download())
        calls.append(
            FakeCheckpointFileHf(
                "Wan-AI/Wan2.2-TI2V-5B",
                "921dbaf3f1674a56f47e83fb80a34bac8a8f203e",
                "Wan2.2_VAE.pth",
            )._download()
        )
        try:
            FakeCheckpointDirHf("unapproved/remote-model")._download()
        except RuntimeError as exc:
            calls.append(str(exc))

    inference_module.main = fake_cosmos_main
    for name in (
        "cosmos_framework",
        "cosmos_framework.utils",
        "cosmos_framework.scripts",
    ):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "cosmos_framework.utils.checkpoint_db", checkpoint_module)
    monkeypatch.setitem(sys.modules, "cosmos_framework.scripts.inference", inference_module)

    wrapper.main()

    assert calls[0] == str(checkpoint.resolve())
    assert calls[1] == str(vae_checkpoint.resolve())
    assert calls[2] == (
        "offline Cosmos inference rejected an undeclared repository: "
        "unapproved/remote-model"
    )
