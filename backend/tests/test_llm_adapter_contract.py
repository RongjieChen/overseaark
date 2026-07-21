from __future__ import annotations

import json
from pathlib import Path


VLLM_VERSION = "0.25.1"
VLLM_WHEEL_SHA256 = "bdffbe35b2c1ab8f2a9dcc337b657261d9b192c92c217e5a2f98a8835fe78daa"


def _read(relative_path: str) -> str:
    return (Path(__file__).resolve().parents[2] / relative_path).read_text(
        encoding="utf-8"
    )


def test_qwen_adapter_uses_local_native_vllm_api_and_json_schema() -> None:
    adapter = _read("scripts/adapters/llm_step.py")

    assert "OVERSEAARK_LLM_BASE_URL" in adapter
    assert "/v1/chat/completions" in adapter
    assert "urllib.request.urlopen" in adapter
    assert '"type": "image_url"' in adapter
    assert "Output JSON Schema" in adapter
    assert '"structured_outputs": {"json": schema}' in adapter
    assert '"enable_thinking": False' in adapter
    assert "_extract_task_result" in adapter
    assert "subprocess" not in adapter
    assert "OVERSEAARK_DOCKER" not in adapter


def test_native_vllm_runtime_is_pinned_cuda_accelerated_and_localhost_only() -> None:
    root = Path(__file__).resolve().parents[2]
    common = _read("scripts/lib/common.sh")
    bootstrap = _read("scripts/bootstrap.sh")
    lifecycle = _read("scripts/lifecycle.sh")
    runtime = _read("scripts/vllm.sh")
    manifest = json.loads((root / "model-manifest.lock.json").read_text(encoding="utf-8"))
    scripts = "\n".join([common, bootstrap, lifecycle, runtime])

    assert f'OVERSEAARK_VLLM_VERSION="${{OVERSEAARK_VLLM_VERSION:-{VLLM_VERSION}}}"' in common
    assert VLLM_WHEEL_SHA256 in common
    assert "manylinux_2_28_aarch64.whl" in common
    assert 'bash "$SCRIPT_DIR/vllm.sh" install' in bootstrap
    assert "torch.cuda.is_available()" in runtime
    assert "--quantization modelopt" in runtime
    assert "--attention-backend flashinfer" in runtime
    assert "--moe-backend marlin" in runtime
    assert "--kv-cache-dtype fp8" in runtime
    assert "--host 127.0.0.1" in runtime
    assert "VLLM_NO_USAGE_STATS=1" in runtime
    assert "HF_HUB_OFFLINE=1" in runtime
    assert "start_vllm" in lifecycle
    assert "OVERSEAARK_LLM_BASE_URL" in common
    assert "http://127.0.0.1:$OVERSEAARK_VLLM_PORT" in common

    primary = manifest["models"][0]
    assert primary["source"] == "nvidia/Qwen3.6-35B-A3B-NVFP4"
    assert primary["revision"] == "491c2f1ea524c639598bf8fa787a93fed5a6fbce"
    assert primary["required"] is True

    assert "OVERSEAARK_DOCKER" not in scripts
    assert "docker exec" not in scripts.lower()
    assert "docker run" not in scripts.lower()


def test_asr_adapter_uses_generic_local_nemo_restore_and_language_tags() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/asr_nemo.py"
    ).read_text(encoding="utf-8")

    assert "nemo_asr.models.ASRModel.restore_from" in adapter
    assert "tagged_language" in adapter
    assert "from_pretrained" not in adapter
