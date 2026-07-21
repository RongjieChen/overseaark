from __future__ import annotations

from pathlib import Path

import pytest

import app.adapters as adapters
from app.adapters import AdapterError, CommandModelHooks, _parse_command_stdout


def test_command_protocol_accepts_final_json_after_nemo_progress() -> None:
    stdout = (
        b"[NeMo I] Model restored locally\n"
        b"Decoding timestep 20\n"
        b'{"audio_path":"voice.wav","duration":4.2}\n'
    )

    assert _parse_command_stdout(stdout) == {
        "audio_path": "voice.wav",
        "duration": 4.2,
    }


def test_command_protocol_does_not_scan_past_a_non_json_final_line() -> None:
    stdout = b'{"premature":"object"}\nCUDA worker crashed\n'

    with pytest.raises(AdapterError, match="did not end with a JSON result"):
        _parse_command_stdout(stdout)


@pytest.mark.asyncio
async def test_heavy_adapter_switch_stops_llama_before_cuda_work(monkeypatch) -> None:
    events: list[str] = []

    async def fake_control(command: str, action: str) -> None:
        events.append(f"control:{action}")

    async def fake_adapter(command: str, payload: dict) -> dict:
        events.append(f"adapter:{command}")
        return {}

    monkeypatch.setattr(adapters, "_run_control_command", fake_control)
    monkeypatch.setattr(adapters, "_run_command", fake_adapter)
    hooks = CommandModelHooks(
        {
            "llm": "llm-adapter",
            "llm_control": "overseaark llm",
            "image": "image-adapter",
            "video": "video-adapter",
            "asr": "asr-adapter",
            "tts": "tts-adapter",
        }
    )

    await hooks.llm("market_positioning", {})
    await hooks.image("prompt", Path("source.png"), Path("output.png"))

    assert events == [
        "control:start",
        "adapter:llm-adapter",
        "control:stop",
        "adapter:image-adapter",
    ]
