"""Small stdlib OverseaArk-compatible mock server for E2E contract tests."""

from __future__ import annotations

import io
import json
import re
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


STAGES = [
    "market_positioning",
    "buyer_persona",
    "multilingual_copy",
    "visual_design",
    "media_production",
    "quality_packaging",
]


@dataclass
class Campaign:
    campaign_id: str
    description: str
    languages: list[str]
    status: str = "queued"
    sequence: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    canceled: bool = False
    failed_once: bool = False


class MockOverseaArkState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.campaigns: dict[str, Campaign] = {}
        self.audit_log: list[dict[str, Any]] = []
        self.fault_once_stage: str | None = None

    def record(self, method: str, path: str) -> None:
        with self.lock:
            self.audit_log.append({"method": method, "path": path, "offline": True})

    def create_campaign(self, description: str, languages: list[str]) -> Campaign:
        campaign = Campaign(str(uuid.uuid4()), description, languages)
        with self.lock:
            self.campaigns[campaign.campaign_id] = campaign
        self._advance(campaign.campaign_id, "queued", "campaign accepted")
        threading.Thread(target=self._run_campaign, args=(campaign.campaign_id,), daemon=True).start()
        return campaign

    def cancel_campaign(self, campaign_id: str) -> bool:
        with self.lock:
            campaign = self.campaigns.get(campaign_id)
            if campaign is None:
                return False
            campaign.canceled = True
        self._advance(campaign_id, "cancelled", "campaign cancelled")
        return True

    def rerun_campaign(self, campaign_id: str) -> Campaign | None:
        with self.lock:
            campaign = self.campaigns.get(campaign_id)
            if campaign is None:
                return None
            description = campaign.description
            languages = list(campaign.languages)
        return self.create_campaign(description, languages)

    def inject_fault_once(self, stage: str) -> None:
        with self.lock:
            self.fault_once_stage = stage

    def _advance(self, campaign_id: str, status: str, message: str, stage: str | None = None) -> None:
        with self.lock:
            campaign = self.campaigns[campaign_id]
            campaign.sequence += 1
            campaign.status = status
            event = {
                "id": campaign.sequence,
                "sequence": campaign.sequence,
                "status": status,
                "type": "stage.retry" if status == "retrying" else "campaign.event",
                "stage": stage,
                "message": message,
                "ts": time.time(),
            }
            campaign.events.append(event)

    def _run_campaign(self, campaign_id: str) -> None:
        time.sleep(0.03)
        for stage in STAGES:
            with self.lock:
                campaign = self.campaigns[campaign_id]
                if campaign.canceled:
                    return
                should_fault = self.fault_once_stage == stage and not campaign.failed_once
                if should_fault:
                    campaign.failed_once = True
                    self.fault_once_stage = None
            if should_fault:
                self._advance(campaign_id, "retrying", f"{stage} failed once; retrying", stage)
                time.sleep(0.02)
            self._advance(campaign_id, "running", f"{stage} complete", stage)
            time.sleep(0.02)
        artifacts: dict[str, Any] = {
            "market_positioning": {"status": "complete"},
            "buyer_persona": {"status": "complete"},
            "multilingual_copy": {
                "copy": {
                    lang: {
                        "headline": f"OverseaArk launch {lang}",
                        "body": f"Localized campaign copy in {lang}",
                    }
                    for lang in self.campaigns[campaign_id].languages
                }
            },
            "visual_design": {"image_path": "visual_design.png"},
            "media_production": {
                "audio": {
                    lang: {"audio_path": f"voice_{lang}.wav"}
                    for lang in self.campaigns[campaign_id].languages
                },
                "video": {"video_path": "campaign_video.mp4"},
            },
            "quality_packaging": {"qc": {"status": "passed"}, "zip_path": "export.zip"},
            "_localized": {
                lang: {
                    "headline": f"OverseaArk launch {lang}",
                    "description": f"Localized campaign copy in {lang}",
                }
                for lang in self.campaigns[campaign_id].languages
            },
        }
        with self.lock:
            self.campaigns[campaign_id].artifacts = artifacts
        self._advance(campaign_id, "completed", "campaign completed")


class MockOverseaArkServer:
    def __init__(self) -> None:
        self.state = MockOverseaArkState()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def start(self) -> "MockOverseaArkServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            server_version = "MockOverseaArk/1.0"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                state.record("GET", parsed.path)
                if parsed.path == "/api/v1/health":
                    self._json({"status": "ok", "service": "overseaark", "offline": True})
                    return
                if parsed.path == "/api/v1/models":
                    self._json({"models": [{"id": "mock-dgx-local", "status": "available"}]})
                    return
                match = re.fullmatch(r"/api/v1/campaigns/([^/]+)", parsed.path)
                if match:
                    self._campaign_json(match.group(1))
                    return
                match = re.fullmatch(r"/api/v1/campaigns/([^/]+)/events", parsed.path)
                if match:
                    self._events(match.group(1), parsed)
                    return
                match = re.fullmatch(r"/api/v1/campaigns/([^/]+)/export", parsed.path)
                if match:
                    self._export_zip(match.group(1))
                    return
                if parsed.path == "/debug/offline-audit":
                    self._json({"external_network_calls": [], "requests": state.audit_log})
                    return
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                state.record("POST", parsed.path)
                if parsed.path == "/api/v1/campaigns":
                    self._create_campaign()
                    return
                match = re.fullmatch(r"/api/v1/campaigns/([^/]+)/cancel", parsed.path)
                if match:
                    ok = state.cancel_campaign(match.group(1))
                    self._json(
                        {"status": "cancelled"} if ok else {"error": "not found"},
                        HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND,
                    )
                    return
                match = re.fullmatch(r"/api/v1/campaigns/([^/]+)/rerun/([^/]+)", parsed.path)
                if match:
                    rerun = state.rerun_campaign(match.group(1))
                    self._json(
                        {"id": rerun.campaign_id, "status": "queued", "from_stage": match.group(2)}
                        if rerun
                        else {"error": "not found"},
                        HTTPStatus.OK if rerun else HTTPStatus.NOT_FOUND,
                    )
                    return
                if parsed.path == "/debug/faults":
                    body = self._read_body()
                    stage = json.loads(body.decode("utf-8") or "{}").get("stage", "localization")
                    state.inject_fault_once(stage)
                    self._json({"status": "armed", "stage": stage})
                    return
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

            def _create_campaign(self) -> None:
                content_type = self.headers.get("Content-Type", "")
                body = self._read_body()
                description = "Generate an overseas campaign"
                languages = ["zh", "en", "ja"]
                if "application/json" in content_type:
                    payload = json.loads(body.decode("utf-8") or "{}")
                    description = payload.get("description", description)
                    languages = payload.get("languages", languages)
                else:
                    text = body.decode("utf-8", errors="ignore")
                    description_match = re.search(r'name="description"\r\n\r\n(.+?)\r\n--', text, re.S)
                    languages_match = re.search(r'name="languages"\r\n\r\n(.+?)\r\n--', text, re.S)
                    if description_match:
                        description = description_match.group(1).strip()
                    if languages_match:
                        languages = [part.strip() for part in languages_match.group(1).split(",") if part.strip()]
                campaign = state.create_campaign(description, languages)
                self._json(self._campaign_payload(campaign), HTTPStatus.CREATED)

            def _campaign_json(self, campaign_id: str) -> None:
                with state.lock:
                    campaign = state.campaigns.get(campaign_id)
                    if campaign is None:
                        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                        return
                    payload = self._campaign_payload(campaign)
                self._json(payload)

            def _campaign_payload(self, campaign: Campaign) -> dict[str, Any]:
                return {
                    "id": campaign.campaign_id,
                    "name": "Mock campaign",
                    "status": campaign.status,
                    "current_stage": None,
                    "description": campaign.description,
                    "source_market": "CN",
                    "target_markets": ["US", "JP"],
                    "languages": campaign.languages,
                    "product_image_path": "mock-upload.png",
                    "stages": [
                        {
                            "name": stage,
                            "status": "succeeded" if campaign.status == "completed" else "pending",
                            "attempts": 1,
                            "output": campaign.artifacts.get(stage, {}),
                        }
                        for stage in STAGES
                    ],
                    "artifacts": campaign.artifacts,
                    "sequence": campaign.sequence,
                }

            def _events(self, campaign_id: str, parsed: Any) -> None:
                last_id = self.headers.get("Last-Event-ID")
                if last_id is None:
                    last_id = parse_qs(parsed.query).get("last_event_id", ["0"])[0]
                minimum = int(last_id or "0")
                with state.lock:
                    campaign = state.campaigns.get(campaign_id)
                    if campaign is None:
                        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                        return
                    events = [event for event in campaign.events if int(event["id"]) > minimum]
                data = "".join(
                    f"id: {event['id']}\nevent: state\ndata: {json.dumps(event)}\n\n"
                    for event in events
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(data.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(data.encode("utf-8"))

            def _export_zip(self, campaign_id: str) -> None:
                with state.lock:
                    campaign = state.campaigns.get(campaign_id)
                    if campaign is None:
                        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                        return
                    artifacts = campaign.artifacts
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", json.dumps({"campaign_id": campaign_id, "stages": STAGES}))
                    for stage in STAGES:
                        archive.writestr(f"stages/{stage}.json", json.dumps(artifacts.get(stage, {})))
                    for lang, artifact in artifacts["_localized"].items():
                        archive.writestr(f"copy/{lang}.json", json.dumps(artifact, ensure_ascii=False))
                        archive.writestr(f"voice_{lang}.wav", f"mock-audio-{lang}".encode("utf-8"))
                    archive.writestr("poster.png", b"mock-poster")
                    archive.writestr("campaign_video.mp4", b"mock-video-480p")
                    archive.writestr("qc_report.json", json.dumps({"status": "passed"}))
                content = buffer.getvalue()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(length) if length else b""

            def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
                content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        return Handler
