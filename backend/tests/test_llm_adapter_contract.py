from __future__ import annotations

from pathlib import Path


def test_step3_adapter_is_offline_multimodal_and_schema_validated() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/llm_step.py"
    ).read_text(encoding="utf-8")

    assert 'MODEL_ID = "stepfun-ai/Step3-VL-10B-FP8"' in adapter
    assert 'local_files_only=True' in adapter
    assert 'trust_remote_code=True' in adapter
    assert 'device_map="auto"' in adapter
    assert '"type": "image"' in adapter
    assert "Output JSON Schema" in adapter
    assert "_extract_task_result" in adapter


def test_asr_adapter_uses_generic_local_nemo_restore_and_language_tags() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/asr_nemo.py"
    ).read_text(encoding="utf-8")

    assert "nemo_asr.models.ASRModel.restore_from" in adapter
    assert "tagged_language" in adapter
    assert "from_pretrained" not in adapter
