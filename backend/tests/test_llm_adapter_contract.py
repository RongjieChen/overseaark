from __future__ import annotations

import json
from pathlib import Path


def test_qwen_adapter_uses_network_isolated_local_vllm_and_schema() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/llm_step.py"
    ).read_text(encoding="utf-8")

    assert 'MODEL_ID = "nvidia/Qwen3.6-35B-A3B-NVFP4"' in adapter
    assert '[docker, "exec", "-i", container' in adapter
    assert 'http://127.0.0.1:__PORT__/v1/chat/completions' in adapter
    assert '"type": "image_url"' in adapter
    assert "Output JSON Schema" in adapter
    assert '"structured_outputs": {"json": schema}' in adapter
    assert '"enable_thinking": False' in adapter
    assert "_extract_task_result" in adapter


def test_vllm_runtime_is_pinned_local_and_network_isolated() -> None:
    root = Path(__file__).resolve().parents[2]
    runtime = (root / "scripts/vllm.sh").read_text(encoding="utf-8")
    common = (root / "scripts/lib/common.sh").read_text(encoding="utf-8")
    manifest = json.loads((root / "model-manifest.lock.json").read_text(encoding="utf-8"))

    assert "--network none" in runtime
    assert "HF_HUB_OFFLINE=1" in runtime
    assert '127.0.0.1:${OVERSEAARK_VLLM_PORT}/health' in runtime
    assert "--quantization modelopt" in runtime
    assert "--moe-backend marlin" in runtime
    assert "sha256:e4f88a835143cd22aee2397a26ec6bb80b3a4a6fe0c882bcbc63822904766089" in common
    primary = manifest["models"][0]
    assert primary["source"] == "nvidia/Qwen3.6-35B-A3B-NVFP4"
    assert primary["revision"] == "491c2f1ea524c639598bf8fa787a93fed5a6fbce"
    assert primary["required"] is True


def test_asr_adapter_uses_generic_local_nemo_restore_and_language_tags() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/asr_nemo.py"
    ).read_text(encoding="utf-8")

    assert "nemo_asr.models.ASRModel.restore_from" in adapter
    assert "tagged_language" in adapter
    assert "from_pretrained" not in adapter
