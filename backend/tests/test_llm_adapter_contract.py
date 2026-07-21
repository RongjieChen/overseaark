from __future__ import annotations

from pathlib import Path


def test_llama_adapter_is_bounded_to_one_noninteractive_turn() -> None:
    adapter = (
        Path(__file__).resolve().parents[2] / "scripts/adapters/llm_step.py"
    ).read_text(encoding="utf-8")

    assert '"--single-turn"' in adapter
    assert '"--simple-io"' in adapter
    assert '"--json-schema"' in adapter
    assert '"--gpu-layers"' in adapter
