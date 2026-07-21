"""End-to-end tests for the OverseaArk service contract."""

from __future__ import annotations

import base64
import io
import json
import os
import time
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any

from mock_overseaark_server import STAGES, MockOverseaArkServer


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "partial"}
API_PREFIX = "/api/v1"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        return json.loads(self.body.decode("utf-8"))


class OverseaArkClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get_json(self, path: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return self.request("GET", path, headers=headers).json()

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        expected: tuple[int, ...] = (200, 201, 202),
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        return self.request("POST", path, body=body, headers=headers, expected=expected).json()

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Response:
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers=headers or {},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as raw:
                response = Response(raw.status, dict(raw.headers.items()), raw.read())
        except urllib.error.HTTPError as error:
            response = Response(error.code, dict(error.headers.items()), error.read())
        if response.status not in expected:
            raise AssertionError(
                f"{method} {path} returned {response.status}, expected {expected}: "
                f"{response.body.decode('utf-8', errors='replace')}"
            )
        return response

    def create_campaign(self, description: str, languages: list[str]) -> str:
        boundary = "----overseaark-e2e-" + uuid.uuid4().hex
        fields = {
            "description": description,
            "languages": ",".join(languages),
        }
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            chunks.append(value.encode("utf-8") + b"\r\n")
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            b'Content-Disposition: form-data; name="product_image"; filename="campaign.png"\r\n'
            b"Content-Type: image/png\r\n\r\n"
        )
        chunks.append(PNG_1X1 + b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        payload = b"".join(chunks)
        response = self.request(
            "POST",
            f"{API_PREFIX}/campaigns",
            body=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            expected=(200, 201, 202),
        ).json()
        return str(response.get("id") or response.get("campaign_id"))

    def wait_for_terminal_status(self, campaign_id: str, timeout: float) -> dict[str, Any]:
        deadline = time.time() + timeout
        last_payload: dict[str, Any] = {}
        while time.time() < deadline:
            last_payload = self.get_json(f"{API_PREFIX}/campaigns/{campaign_id}")
            if str(last_payload.get("status") or last_payload.get("state")) in TERMINAL_STATUSES:
                return last_payload
            time.sleep(0.25)
        raise AssertionError(f"campaign {campaign_id} did not finish in {timeout}s; last={last_payload}")

    def events(self, campaign_id: str, last_event_id: int | None = None) -> list[dict[str, Any]]:
        headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else None
        response = self.request("GET", f"{API_PREFIX}/campaigns/{campaign_id}/events", headers=headers)
        return parse_sse(response.body.decode("utf-8"))


def parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        if not block:
            continue
        data_lines = [line.removeprefix("data:").strip() for line in block.splitlines() if line.startswith("data:")]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


class OverseaArkE2ETest(unittest.TestCase):
    server: MockOverseaArkServer | None = None
    client: OverseaArkClient
    languages: list[str]
    timeout: float

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("OVERSEAARK_E2E_MOCK") == "1":
            cls.server = MockOverseaArkServer().start()
            base_url = cls.server.base_url
        else:
            base_url = os.environ.get("OVERSEAARK_BASE_URL", "http://127.0.0.1:8000")
        cls.client = OverseaArkClient(base_url)
        cls.languages = [
            lang.strip()
            for lang in os.environ.get("OVERSEAARK_E2E_EXPECT_LANGS", "zh,en,ja").split(",")
            if lang.strip()
        ]
        cls.timeout = float(os.environ.get("OVERSEAARK_E2E_TIMEOUT", "60"))

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.stop()

    def create_successful_campaign(self) -> tuple[str, dict[str, Any]]:
        campaign_id = self.client.create_campaign(
            "Create an overseas launch campaign from this image.",
            self.languages,
        )
        self.assertTrue(campaign_id)
        payload = self.client.wait_for_terminal_status(campaign_id, self.timeout)
        self.assertEqual(payload.get("status") or payload.get("state"), "completed")
        return campaign_id, payload

    def test_health_endpoint_returns_healthy_status(self) -> None:
        payload = self.client.get_json(f"{API_PREFIX}/health")
        self.assertIn(str(payload.get("status")).lower(), {"ok", "healthy", "ready"})

    def test_models_endpoint_returns_at_least_one_available_model(self) -> None:
        payload = self.client.get_json(f"{API_PREFIX}/models")
        models = payload.get("models") or payload.get("data")
        if models is not None:
            self.assertGreaterEqual(len(models), 1)
            return
        configured_models = [payload.get(key) for key in ("llm", "image", "video", "asr", "tts")]
        self.assertTrue(any(configured_models))

    def test_create_campaign_accepts_image_and_description(self) -> None:
        campaign_id = self.client.create_campaign("Create a launch campaign.", self.languages)
        self.assertTrue(campaign_id)

    def test_campaign_state_sequence_increases_monotonically(self) -> None:
        campaign_id, _payload = self.create_successful_campaign()
        events = self.client.events(campaign_id)
        sequences = [int(event["sequence"]) for event in events]
        self.assertEqual(sequences, sorted(set(sequences)))

    def test_sse_resume_returns_events_after_last_event_id(self) -> None:
        campaign_id, _payload = self.create_successful_campaign()
        events = self.client.events(campaign_id)
        self.assertGreaterEqual(len(events), 2)
        resumed = self.client.events(campaign_id, last_event_id=int(events[0]["sequence"]))
        self.assertEqual([event["sequence"] for event in resumed], [event["sequence"] for event in events[1:]])

    def test_successful_campaign_returns_all_six_stage_outputs(self) -> None:
        _campaign_id, payload = self.create_successful_campaign()
        stages = payload.get("stages") or []
        self.assertEqual([stage.get("name") for stage in stages], STAGES)

    def test_successful_campaign_returns_localized_artifacts(self) -> None:
        _campaign_id, payload = self.create_successful_campaign()
        copy = ((payload.get("artifacts") or {}).get("multilingual_copy") or {}).get("copy") or {}
        self.assertEqual(set(copy), set(self.languages))

    def test_export_zip_contains_manifest_stages_and_localized_artifacts(self) -> None:
        campaign_id, _payload = self.create_successful_campaign()
        response = self.client.request("GET", f"{API_PREFIX}/campaigns/{campaign_id}/export")
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            names = set(archive.namelist())
        expected = {"manifest.json", "poster.png", "campaign_video.mp4", "qc_report.json"}
        expected.update(f"stages/{stage}.json" for stage in STAGES)
        for lang in self.languages:
            expected.update(
                {
                    f"copy/{lang}.json",
                    f"voice_{lang}.wav",
                }
            )
        self.assertTrue(expected.issubset(names), f"missing {sorted(expected - names)}")

    def test_cancel_moves_campaign_to_canceled_state(self) -> None:
        campaign_id = self.client.create_campaign("Create a cancelable campaign.", self.languages)
        payload = self.client.post_json(f"{API_PREFIX}/campaigns/{campaign_id}/cancel", {})
        self.assertEqual(payload.get("status") or payload.get("state"), "cancelled")

    def test_rerun_creates_successful_campaign_after_cancel(self) -> None:
        campaign_id = self.client.create_campaign("Create a campaign to rerun.", self.languages)
        self.client.post_json(f"{API_PREFIX}/campaigns/{campaign_id}/cancel", {})
        rerun = self.client.post_json(f"{API_PREFIX}/campaigns/{campaign_id}/rerun/market_positioning", {})
        rerun_id = str(rerun.get("id") or rerun.get("campaign_id"))
        payload = self.client.wait_for_terminal_status(rerun_id, self.timeout)
        self.assertEqual(payload.get("status") or payload.get("state"), "completed")

    def test_one_retry_fault_injection_finishes_partial_or_succeeded(self) -> None:
        if os.environ.get("OVERSEAARK_E2E_SKIP_FAULTS") == "1":
            self.skipTest("fault injection endpoint disabled")
        response = self.client.request(
            "POST",
            "/debug/faults",
            body=json.dumps({"stage": "multilingual_copy", "mode": "fail_once"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            expected=(200, 201, 202, 404, 405),
        )
        if response.status in {404, 405}:
            self.skipTest("fault injection endpoint unavailable")
        campaign_id = self.client.create_campaign("Create a campaign with one transient fault.", self.languages)
        payload = self.client.wait_for_terminal_status(campaign_id, self.timeout)
        self.assertIn(payload.get("status") or payload.get("state"), {"partial", "completed"})

    def test_fault_injection_emits_retry_state_before_terminal_state(self) -> None:
        if os.environ.get("OVERSEAARK_E2E_SKIP_FAULTS") == "1":
            self.skipTest("fault injection endpoint disabled")
        response = self.client.request(
            "POST",
            "/debug/faults",
            body=json.dumps({"stage": "multilingual_copy", "mode": "fail_once"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            expected=(200, 201, 202, 404, 405),
        )
        if response.status in {404, 405}:
            self.skipTest("fault injection endpoint unavailable")
        campaign_id = self.client.create_campaign("Create a campaign with retry telemetry.", self.languages)
        self.client.wait_for_terminal_status(campaign_id, self.timeout)
        events = self.client.events(campaign_id)
        event_types = [event.get("type") for event in events]
        statuses = [event.get("status") for event in events]
        self.assertTrue("stage.retry" in event_types or "retrying" in statuses)

    def test_offline_endpoint_audit_reports_no_external_network_calls(self) -> None:
        if os.environ.get("OVERSEAARK_E2E_SKIP_OFFLINE_AUDIT") == "1":
            self.skipTest("offline audit endpoint disabled")
        response = self.client.request("GET", "/debug/offline-audit", expected=(200, 404, 405))
        content_type = response.headers.get("Content-Type", response.headers.get("content-type", ""))
        if response.status in {404, 405} or "application/json" not in content_type:
            self.skipTest("offline audit endpoint unavailable")
        payload = response.json()
        self.assertEqual(payload.get("external_network_calls", []), [])

    def test_three_sequential_campaign_smoke_runs_succeed(self) -> None:
        results = []
        for index in range(3):
            campaign_id = self.client.create_campaign(f"Smoke campaign {index + 1}.", self.languages)
            payload = self.client.wait_for_terminal_status(campaign_id, self.timeout)
            results.append(payload.get("status") or payload.get("state"))
        self.assertEqual(results, ["completed", "completed", "completed"])
