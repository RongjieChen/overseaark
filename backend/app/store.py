from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    STAGE_ORDER,
    CampaignCreate,
    CampaignDetail,
    CampaignEvent,
    CampaignStatus,
    CampaignSummary,
    StageName,
    StageRecord,
    StageStatus,
)


def now_utc() -> datetime:
    return datetime.now(UTC)


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source_market TEXT NOT NULL,
                    target_markets TEXT NOT NULL,
                    languages TEXT NOT NULL,
                    product_image_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    current_stage TEXT,
                    error TEXT,
                    artifacts TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stages (
                    campaign_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    error TEXT,
                    output TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY (campaign_id, name),
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(campaigns)")}
            if "cancel_requested" not in columns:
                conn.execute(
                    "ALTER TABLE campaigns ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
                )

    def create_campaign(self, payload: CampaignCreate) -> CampaignDetail:
        campaign_id = str(uuid.uuid4())
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO campaigns
                (id, name, description, source_market, target_markets, languages, product_image_path,
                 status, cancel_requested, current_stage, error, artifacts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    payload.name,
                    payload.description,
                    payload.source_market,
                    json.dumps(payload.target_markets),
                    json.dumps(payload.languages),
                    payload.product_image_path,
                    CampaignStatus.queued.value,
                    None,
                    None,
                    "{}",
                    timestamp,
                    timestamp,
                ),
            )
            for stage in STAGE_ORDER:
                conn.execute(
                    """
                    INSERT INTO stages
                    (campaign_id, name, status, attempts, error, output, started_at, finished_at)
                    VALUES (?, ?, ?, 0, NULL, '{}', NULL, NULL)
                    """,
                    (campaign_id, stage.value, StageStatus.pending.value),
                )
            conn.commit()
        self.add_event(campaign_id, "campaign.created", "Campaign queued")
        return self.get_campaign(campaign_id)

    def list_campaigns(self) -> list[CampaignSummary]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
        return [self._summary_from_row(row) for row in rows]

    def get_campaign(self, campaign_id: str) -> CampaignDetail:
        with self._connect() as conn:
            campaign = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if campaign is None:
                raise KeyError(campaign_id)
            stages = conn.execute(
                "SELECT * FROM stages WHERE campaign_id = ? ORDER BY rowid", (campaign_id,)
            ).fetchall()
        return self._detail_from_rows(campaign, stages)

    def set_campaign_status(
        self,
        campaign_id: str,
        status: CampaignStatus,
        current_stage: StageName | None = None,
        error: str | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> None:
        fields = ["status = ?", "current_stage = ?", "error = ?", "updated_at = ?"]
        values: list[Any] = [status.value, current_stage.value if current_stage else None, error, now_utc().isoformat()]
        if artifacts is not None:
            fields.append("artifacts = ?")
            values.append(json.dumps(artifacts))
        values.append(campaign_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE campaigns SET {', '.join(fields)} "
                "WHERE id = ? AND (cancel_requested = 0 OR ? = ?)",
                (*values, status.value, CampaignStatus.cancelled.value),
            )
            conn.commit()

    def mark_stage(
        self,
        campaign_id: str,
        stage: StageName,
        status: StageStatus,
        attempts: int | None = None,
        error: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        assignments = ["status = ?", "error = ?"]
        values: list[Any] = [status.value, error]
        if attempts is not None:
            assignments.append("attempts = ?")
            values.append(attempts)
        if output is not None:
            assignments.append("output = ?")
            values.append(json.dumps(output))
        if status == StageStatus.running:
            assignments.append("started_at = ?")
            values.append(now_utc().isoformat())
        if status in {StageStatus.succeeded, StageStatus.failed, StageStatus.skipped}:
            assignments.append("finished_at = ?")
            values.append(now_utc().isoformat())
        values.extend([campaign_id, stage.value])
        with self._connect() as conn:
            conn.execute(
                f"UPDATE stages SET {', '.join(assignments)} WHERE campaign_id = ? AND name = ?",
                values,
            )
            conn.commit()

    def increment_stage_attempts(self, campaign_id: str, stage: StageName) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM stages WHERE campaign_id = ? AND name = ?",
                (campaign_id, stage.value),
            ).fetchone()
            if row is None:
                raise KeyError(f"{campaign_id}:{stage.value}")
            attempts = int(row["attempts"]) + 1
            conn.execute(
                "UPDATE stages SET attempts = ? WHERE campaign_id = ? AND name = ?",
                (attempts, campaign_id, stage.value),
            )
            conn.commit()
        return attempts

    def reset_campaign_for_rerun(self, campaign_id: str, from_stage: StageName) -> None:
        timestamp = now_utc().isoformat()
        stage_index = STAGE_ORDER.index(from_stage)
        reset_stages = [stage.value for stage in STAGE_ORDER[stage_index:]]
        placeholders = ",".join("?" for _ in reset_stages)
        with self._connect() as conn:
            current = conn.execute(
                "SELECT artifacts FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if current is None:
                raise KeyError(campaign_id)
            artifacts = json.loads(current["artifacts"])
            for stage in reset_stages:
                artifacts.pop(stage, None)
            conn.execute(
                """
                UPDATE campaigns
                SET status = ?, cancel_requested = 0, current_stage = NULL, error = NULL,
                    artifacts = ?, updated_at = ?
                WHERE id = ?
                """,
                (CampaignStatus.queued.value, json.dumps(artifacts), timestamp, campaign_id),
            )
            conn.execute(
                f"""
                UPDATE stages
                SET status = ?, attempts = 0, error = NULL, output = '{{}}',
                    started_at = NULL, finished_at = NULL
                WHERE campaign_id = ? AND name IN ({placeholders})
                """,
                (StageStatus.pending.value, campaign_id, *reset_stages),
            )
            conn.commit()
        self.add_event(campaign_id, "campaign.rerun", f"Campaign queued for rerun from {from_stage.value}")

    def request_cancel(self, campaign_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE campaigns
                SET cancel_requested = 1, status = ?, current_stage = NULL, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    CampaignStatus.cancelled.value,
                    "Cancellation requested",
                    now_utc().isoformat(),
                    campaign_id,
                ),
            )
            conn.execute(
                """
                UPDATE stages
                SET status = ?, error = ?, finished_at = ?
                WHERE campaign_id = ? AND status IN (?, ?)
                """,
                (
                    StageStatus.skipped.value,
                    "Cancelled",
                    now_utc().isoformat(),
                    campaign_id,
                    StageStatus.pending.value,
                    StageStatus.running.value,
                ),
            )
            conn.commit()
        self.add_event(campaign_id, "campaign.cancelled", "Cancellation requested")

    def is_cancel_requested(self, campaign_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        if row is None:
            raise KeyError(campaign_id)
        return bool(row["cancel_requested"])

    def add_event(
        self,
        campaign_id: str,
        event_type: str,
        message: str,
        stage: StageName | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CampaignEvent:
        campaign = self.get_campaign(campaign_id)
        created_at = now_utc()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (campaign_id, type, status, stage, message, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    event_type,
                    campaign.status.value,
                    stage.value if stage else None,
                    message,
                    json.dumps(payload or {}),
                    created_at.isoformat(),
                ),
            )
            sequence = int(cursor.lastrowid)
            conn.commit()
        return CampaignEvent(
            sequence=sequence,
            campaign_id=campaign_id,
            type=event_type,
            status=campaign.status,
            stage=stage,
            message=message,
            created_at=created_at,
            payload=payload or {},
        )

    def list_events(self, campaign_id: str, after_id: int = 0) -> list[tuple[int, CampaignEvent]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE campaign_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (campaign_id, after_id),
            ).fetchall()
        return [
            (
                int(row["id"]),
                CampaignEvent(
                    sequence=int(row["id"]),
                    campaign_id=row["campaign_id"],
                    type=row["type"],
                    status=CampaignStatus(row["status"]),
                    stage=StageName(row["stage"]) if row["stage"] else None,
                    message=row["message"],
                    payload=json.loads(row["payload"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                ),
            )
            for row in rows
        ]

    def _summary_from_row(self, row: sqlite3.Row) -> CampaignSummary:
        return CampaignSummary(
            id=row["id"],
            name=row["name"],
            status=CampaignStatus(row["status"]),
            current_stage=StageName(row["current_stage"]) if row["current_stage"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _detail_from_rows(self, row: sqlite3.Row, stage_rows: list[sqlite3.Row]) -> CampaignDetail:
        summary = self._summary_from_row(row)
        return CampaignDetail(
            **summary.model_dump(),
            description=row["description"],
            source_market=row["source_market"],
            target_markets=json.loads(row["target_markets"]),
            languages=json.loads(row["languages"]),
            product_image_path=row["product_image_path"],
            error=row["error"],
            artifacts=json.loads(row["artifacts"]),
            stages=[
                StageRecord(
                    name=StageName(stage["name"]),
                    status=StageStatus(stage["status"]),
                    attempts=int(stage["attempts"]),
                    error=stage["error"],
                    output=json.loads(stage["output"]),
                    started_at=datetime.fromisoformat(stage["started_at"])
                    if stage["started_at"]
                    else None,
                    finished_at=datetime.fromisoformat(stage["finished_at"])
                    if stage["finished_at"]
                    else None,
                )
                for stage in stage_rows
            ],
        )
