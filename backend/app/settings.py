from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    data_dir: Path = Path(os.getenv("OVERSEAARK_DATA_DIR", ".overseaark-data"))
    adapter_mode: str = os.getenv("OVERSEAARK_ADAPTER_MODE", "mock")
    resident_adapters: str = os.getenv("OVERSEAARK_RESIDENT_ADAPTERS", "asr,tts")
    keep_vllm_resident: bool = os.getenv("OVERSEAARK_KEEP_VLLM_RESIDENT", "0") == "1"
    llm_command: str | None = os.getenv("OVERSEAARK_LLM_COMMAND")
    llm_control_command: str | None = os.getenv("OVERSEAARK_LLM_CONTROL_COMMAND")
    image_command: str | None = os.getenv("OVERSEAARK_IMAGE_COMMAND")
    video_command: str | None = os.getenv("OVERSEAARK_VIDEO_COMMAND")
    asr_command: str | None = os.getenv("OVERSEAARK_ASR_COMMAND")
    tts_command: str | None = os.getenv("OVERSEAARK_TTS_COMMAND")
    offline_only: bool = os.getenv("OVERSEAARK_OFFLINE_ONLY", "1") != "0"
    frontend_dist_dir: Path | None = (
        Path(os.environ["OVERSEAARK_FRONTEND_DIST_DIR"])
        if "OVERSEAARK_FRONTEND_DIST_DIR" in os.environ
        else None
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "overseaark.sqlite3"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


def get_settings() -> Settings:
    return Settings()
