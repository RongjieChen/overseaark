from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path


VLLM_MODEL_REVISION = "491c2f1ea524c639598bf8fa787a93fed5a6fbce"
VLLM_WHEEL_SHA256 = "bdffbe35b2c1ab8f2a9dcc337b657261d9b192c92c217e5a2f98a8835fe78daa"


def _read(relative_path: str) -> str:
    return (Path(__file__).resolve().parents[2] / relative_path).read_text(
        encoding="utf-8"
    )


def _load_llm_adapter():
    adapter_dir = Path(__file__).resolve().parents[2] / "scripts" / "adapters"
    sys.path.insert(0, str(adapter_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "overseaark_llm_step", adapter_dir / "llm_step.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(adapter_dir))


def test_qwen_adapter_uses_local_vllm_openai_chat_api_and_json_schema() -> None:
    adapter = _read("scripts/adapters/llm_step.py")

    assert "OVERSEAARK_LLM_BASE_URL" in adapter
    assert 'http://127.0.0.1:8011' in adapter
    assert "/v1/chat/completions" in adapter
    assert "urllib.request.urlopen" in adapter
    assert "OVERSEAARK_VLLM_API_KEY_FILE" in adapter
    assert 'headers["Authorization"] = f"Bearer {key}"' in adapter
    assert '"type": "image_url"' in adapter
    assert "Output JSON Schema" in adapter
    assert '"type": "json_schema"' in adapter
    assert '"json_schema": {"name": task, "strict": True, "schema": schema}' in adapter
    assert '"chat_template_kwargs": {"enable_thinking": False}' in adapter
    assert "_extract_task_result" in adapter
    assert "_local_vllm_endpoint" in adapter
    assert 'parsed.hostname not in {"127.0.0.1", "localhost"}' in adapter
    assert "subprocess" not in adapter
    assert "OVERSEAARK_DOCKER" not in adapter


def test_multilingual_schema_is_language_exact_and_has_a_complete_token_budget(
    monkeypatch,
) -> None:
    adapter = _load_llm_adapter()
    monkeypatch.delenv("OVERSEAARK_LLM_TOKENS", raising=False)

    schema = adapter._schema_for_task(
        "multilingual_copy", {"languages": ["zh", "en", "ja", "zh"]}
    )
    copy_schema = schema["properties"]["copy"]

    assert copy_schema["required"] == ["zh", "en", "ja"]
    assert set(copy_schema["properties"]) == {"zh", "en", "ja"}
    assert copy_schema["additionalProperties"] is False
    assert adapter._task_token_limit("multilingual_copy") == 3072


def test_native_vllm_runtime_is_pinned_cuda_accelerated_and_localhost_only() -> None:
    root = Path(__file__).resolve().parents[2]
    common = _read("scripts/lib/common.sh")
    bootstrap = _read("scripts/bootstrap.sh")
    lifecycle = _read("scripts/lifecycle.sh")
    runtime = _read("scripts/vllm_server.sh")
    manifest = json.loads((root / "model-manifest.lock.json").read_text(encoding="utf-8"))
    scripts = "\n".join([common, bootstrap, lifecycle, runtime])

    assert VLLM_MODEL_REVISION in common
    assert VLLM_WHEEL_SHA256 in common
    assert "https://github.com/vllm-project/vllm/releases/download/v0.25.1/" in common
    assert "https://pypi.tuna.tsinghua.edu.cn/simple" in common
    assert "https://hf-mirror.com" in common
    assert 'bash "$SCRIPT_DIR/vllm_server.sh" install' in bootstrap
    assert "vllm.__version__.split(\"+\")[0] == expected" in runtime
    assert '"Linux" && "$(uname -m)" == "aarch64"' in runtime
    assert "Python 3.12 is required for native vLLM" in runtime
    assert "sha256sum -c -" in runtime
    assert "vllm-0.25.1%2Bcu129-cp38-abi3-manylinux_2_28_aarch64.whl" in common
    assert "VLLM_API_KEY=%q" in runtime
    assert "serve %q" in runtime
    assert "--served-model-name %q" in runtime
    assert "--host 127.0.0.1" in runtime
    assert "--port %q" in runtime
    assert "--tensor-parallel-size 1" in runtime
    assert "--kv-cache-dtype fp8" in runtime
    assert "--attention-backend flashinfer" in runtime
    assert "--moe-backend marlin" in runtime
    assert "--gpu-memory-utilization %q" in runtime
    assert "--max-model-len %q" in runtime
    assert "--max-num-seqs %q" in runtime
    assert "--max-num-batched-tokens %q" in runtime
    assert "--enable-chunked-prefill --async-scheduling --enable-prefix-caching" in runtime
    assert '"method":"mtp"' in runtime
    assert "--load-format fastsafetensors --reasoning-parser qwen3" in runtime
    assert "--tool-call-parser qwen3_xml --enable-auto-tool-choice" in runtime
    assert "HF_HUB_OFFLINE=1" in runtime
    assert "TRANSFORMERS_OFFLINE=1" in runtime
    assert "HF_DATASETS_OFFLINE=1" in runtime
    assert "VLLM_NO_USAGE_STATS=1" in runtime
    assert "start_vllm" in lifecycle
    assert "OVERSEAARK_LLM_BASE_URL" in common
    assert "http://127.0.0.1:$OVERSEAARK_VLLM_PORT" in common
    assert "OVERSEAARK_VLLM_STARTUP_TIMEOUT" in common
    assert "OVERSEAARK_VLLM_STARTUP_TIMEOUT must be a positive integer" in lifecycle

    primary = manifest["models"][0]
    assert primary["id"] == "qwen3.6-35b-a3b-nvfp4"
    assert primary["provider"] == "huggingface"
    assert primary["source"] == "nvidia/Qwen3.6-35B-A3B-NVFP4"
    assert primary["revision"] == VLLM_MODEL_REVISION
    assert primary["local_dir"] == "nvidia/qwen3.6-35b-a3b-nvfp4"
    assert {item["path"] for item in primary["files"]} == {
        "chat_template.jinja",
        "config.json",
        "configuration.json",
        "generation_config.json",
        "hf_quant_config.json",
        "model-00001-of-00003.safetensors",
        "model-00002-of-00003.safetensors",
        "model-00003-of-00003.safetensors",
        "model.safetensors.index.json",
        "preprocessor_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "video_preprocessor_config.json",
        "vocab.json",
    }
    assert len(primary["files"]) == 14
    assert all(item["required"] is True for item in primary["files"])
    assert primary["required"] is True

    assert "OVERSEAARK_DOCKER" not in scripts
    assert "docker exec" not in scripts.lower()
    assert "docker run" not in scripts.lower()
    assert "llama_server" not in scripts
    assert "llama.cpp" not in scripts


def test_cosmos_inference_dependency_is_installed_without_training_extra() -> None:
    bootstrap = _read("scripts/bootstrap.sh")

    assert '"iopath==0.1.10"' in bootstrap
    assert "--group=cu130" in bootstrap
    assert "cu130-train" not in bootstrap


def test_asr_adapter_uses_generic_local_nemo_restore_and_language_tags() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/asr_nemo.py"
    ).read_text(encoding="utf-8")

    assert "nemo_asr.models.ASRModel.restore_from" in adapter
    assert "RNNTPromptTranscribeConfig" in adapter
    assert "use_lhotse=False" in adapter
    assert "override_config=transcribe_config" in adapter
    assert 're.fullmatch(r"<[a-z]{2}(?:-[A-Z]{2})?>", segment_text)' in adapter
    assert "tagged_language" in adapter
    assert "from_pretrained" not in adapter


def test_audio_runtimes_are_pinned_to_checkpoint_compatible_nemo_versions() -> None:
    bootstrap = _read("scripts/bootstrap.sh")
    common = _read("scripts/lib/common.sh")

    assert ".venv-asr/bin/python" in common
    assert ".venv-tts/bin/python" in common
    assert "nemo_toolkit[tts]==2.7.3" in bootstrap
    assert "NVIDIA-NeMo/NeMo.git@93b15b1f423ddc8e0d189810fdd8304091d9b1bd" in bootstrap
    assert "nemo_toolkit[asr,tts]" not in bootstrap


def test_magpie_uses_a_locked_local_nanocodec_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    adapter = _read("scripts/adapters/tts_magpie.py")
    manifest = json.loads((root / "model-manifest.lock.json").read_text(encoding="utf-8"))
    codec = next(
        model
        for model in manifest["models"]
        if model["id"] == "nemo-nano-codec-22khz-1.89kbps-21.5fps"
    )

    assert 'config.codecmodel_path = str(codec_path)' in adapter
    assert 'models_root() / "google/byt5-small"' in adapter
    assert 'tokenizer_config.pretrained_model = str(tokenizer_path)' in adapter
    assert 'tokenizers.get("japanese_phoneme")' in adapter
    assert 'if language == "ja"' in adapter
    assert 'payload.get("apply_TN", False)' in adapter
    assert "pyopenjtalk.OPEN_JTALK_DICT_DIR.decode()" in adapter
    assert "prepare_open_jtalk_dictionary" in _read("scripts/bootstrap.sh")
    assert "fe6ba0e43542cef98339abdffd903e062008ea170b04e7e2a35da805902f382a" in _read(
        "scripts/bootstrap.sh"
    )
    assert "override_config_path=config" in adapter
    assert "codec_config.discriminator = None" in adapter
    assert 'codec_config.use_scl_loss = False' in adapter
    assert codec["revision"] == "3c482a402a3c4cf33690a2c0f0a7d41afea6bd6a"
    assert codec["files"][0]["sha256"] == (
        "28c2518de3e3d5a2c7d9bca40a7ebc0644eb76c60b890970365325bdd8e9f099"
    )
    byt5 = next(model for model in manifest["models"] if model["id"] == "byt5-small-tokenizer")
    assert byt5["revision"] == "68377bdc18a2ffec8a0533fef03b1c513a4dd49d"
    assert all(not item["path"].endswith((".bin", ".safetensors")) for item in byt5["files"])


def test_step1x_reserves_typography_for_deterministic_pillow_layout() -> None:
    adapter = _read("scripts/adapters/image_step1x.py")

    assert "Do not render text, letters, logos, captions, or watermarks" in adapter
    assert "typography is added after generation" in adapter
    assert "prompt=generation_prompt" in adapter
