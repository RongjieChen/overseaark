from __future__ import annotations

from pathlib import Path


def test_llama_adapter_is_noninteractive_and_schema_validated() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/llm_step.py"
    ).read_text(encoding="utf-8")

    assert '"--no-conversation"' in adapter
    assert '"--simple-io"' in adapter
    assert '"--single-turn"' in adapter
    assert '"--json-schema"' in adapter
    assert '"--gpu-layers"' in adapter
    assert "_extract_task_result" in adapter


def test_asr_adapter_uses_generic_local_nemo_restore_and_language_tags() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/asr_nemo.py"
    ).read_text(encoding="utf-8")

    assert "nemo_asr.models.ASRModel.restore_from" in adapter
    assert "tagged_language" in adapter
    assert "from_pretrained" not in adapter
