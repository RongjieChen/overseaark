from __future__ import annotations

import json
from pathlib import Path


LLAMA_REVISION = "76f46ad29d61fd8c1401e8221842934bf62a6064"


def _read(relative_path: str) -> str:
    return (Path(__file__).resolve().parents[2] / relative_path).read_text(
        encoding="utf-8"
    )


def test_qwen_adapter_uses_local_llama_cpp_api_and_json_schema() -> None:
    adapter = _read("scripts/adapters/llm_step.py")

    assert "OVERSEAARK_LLM_BASE_URL" in adapter
    assert "/v1/chat/completions" in adapter
    assert "urllib.request.urlopen" in adapter
    assert 'headers["Authorization"] = f"Bearer {key}"' in adapter
    assert '"type": "image_url"' in adapter
    assert "Output JSON Schema" in adapter
    assert '"type": "json_schema"' in adapter
    assert '"json_schema": {"name": task, "strict": True, "schema": schema}' in adapter
    assert '"enable_thinking": False' in adapter
    assert "_extract_task_result" in adapter
    assert "subprocess" not in adapter
    assert "OVERSEAARK_DOCKER" not in adapter


def test_native_llama_runtime_is_pinned_cuda_accelerated_and_localhost_only() -> None:
    root = Path(__file__).resolve().parents[2]
    common = _read("scripts/lib/common.sh")
    bootstrap = _read("scripts/bootstrap.sh")
    lifecycle = _read("scripts/lifecycle.sh")
    runtime = _read("scripts/llama_server.sh")
    manifest = json.loads((root / "model-manifest.lock.json").read_text(encoding="utf-8"))
    scripts = "\n".join([common, bootstrap, lifecycle, runtime])

    assert LLAMA_REVISION in common
    assert 'bash "$SCRIPT_DIR/llama_server.sh" install' in bootstrap
    assert "-DGGML_CUDA=ON" in runtime
    assert "-DLLAMA_CURL=OFF" in runtime
    assert "--model %q --mmproj %q" in runtime
    assert "--gpu-layers all" in runtime
    assert "--flash-attn on" in runtime
    assert "--reasoning off" in runtime
    assert "--host 127.0.0.1" in runtime
    assert "--api-key-file %q" in runtime
    assert "--cors-origins localhost --no-cors-credentials" in runtime
    assert "HF_HUB_OFFLINE=1" in runtime
    assert "start_llama" in lifecycle
    assert "OVERSEAARK_LLM_BASE_URL" in common
    assert "http://127.0.0.1:$OVERSEAARK_LLAMA_PORT" in common

    primary = manifest["models"][0]
    assert primary["provider"] == "modelscope"
    assert primary["source"] == "ggml-org/Qwen3.6-35B-A3B-GGUF"
    assert primary["revision"] == "37b9ed4ed8b3942a5ac69bffb490a5d25acdad4e"
    assert {item["path"] for item in primary["files"]} == {
        "Qwen3.6-35B-A3B-Q4_K_M.gguf",
        "mmproj-Qwen3.6-35B-A3B-BF16.gguf",
    }
    assert primary["required"] is True

    assert "OVERSEAARK_DOCKER" not in scripts
    assert "docker exec" not in scripts.lower()
    assert "docker run" not in scripts.lower()


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
