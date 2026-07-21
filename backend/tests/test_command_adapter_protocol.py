from __future__ import annotations

import pytest

from app.adapters import AdapterError, _parse_command_stdout


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
