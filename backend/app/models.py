from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CampaignStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"


class StageStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class StageName(StrEnum):
    market_positioning = "market_positioning"
    buyer_persona = "buyer_persona"
    multilingual_copy = "multilingual_copy"
    visual_design = "visual_design"
    media_production = "media_production"
    quality_packaging = "quality_packaging"


STAGE_ORDER: tuple[StageName, ...] = (
    StageName.market_positioning,
    StageName.buyer_persona,
    StageName.multilingual_copy,
    StageName.visual_design,
    StageName.media_production,
    StageName.quality_packaging,
)

DEFAULT_LANGUAGES: tuple[str, ...] = ("zh", "en", "ja")


class TranscriptionResponse(BaseModel):
    text: str
    language: str
    segments: list[dict[str, Any]]
    model: str


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=5, max_length=2000)
    audio_transcription: str = Field(default="", max_length=4000)
    source_market: str = "CN"
    target_markets: list[str] = Field(default_factory=lambda: ["US", "JP"])
    languages: list[str] = Field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    product_image_path: str


class CampaignSummary(BaseModel):
    id: str
    name: str
    status: CampaignStatus
    current_stage: StageName | None
    created_at: datetime
    updated_at: datetime


class StageRecord(BaseModel):
    name: StageName
    status: StageStatus
    attempts: int
    error: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CampaignDetail(CampaignSummary):
    description: str
    audio_transcription: str
    source_market: str
    target_markets: list[str]
    languages: list[str]
    product_image_path: str
    stages: list[StageRecord]
    error: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)


class CampaignEvent(BaseModel):
    sequence: int
    campaign_id: str
    type: str
    status: CampaignStatus
    stage: StageName | None = None
    message: str
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    llm: str
    image: str
    video: str
    asr: str
    tts: str
    mode: str
    offline: bool
    serialized: bool = True


class HealthResponse(BaseModel):
    status: str
    storage_path: str
    model_status: str = "ready"
