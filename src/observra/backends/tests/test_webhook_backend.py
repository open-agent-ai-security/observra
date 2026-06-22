"""Tests for WebhookBackend."""

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import patch

import pytest

from observra.backends.webhook import WebhookBackend
from observra.core.events import TelemetryEvent


def _make_event(**kwargs) -> TelemetryEvent:
    defaults = {
        "event_id": "evt-001",
        "event_type": "model_response",
        "timestamp": time.time(),
        "session_id": "sess-abc",
        "trace_id": "trace-123",
        "span_id": "span-456",
        "framework": "adk",
        "agent_name": "test-agent",
        "model_name": "gemini-2.5-flash",
        "tool_name": None,
        "data": {"input_tokens": 100, "output_tokens": 50},
    }
    defaults.update(kwargs)
    return TelemetryEvent(**defaults)


class _RecordingHandler(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _RecordingHandler.received.append(
            {
                "body": json.loads(body),
                "headers": dict(self.headers),
            }
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture()
def webhook_server():
    _RecordingHandler.received = []
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/events"
    server.shutdown()
    server.server_close()


class TestWebhookBackend:
    def test_single_event_post(self, webhook_server):
        backend = WebhookBackend(url=webhook_server)
        event = _make_event()
        backend.write(event)

        assert len(_RecordingHandler.received) == 1
        payload = _RecordingHandler.received[0]["body"]
        assert payload["event_type"] == "model_response"
        assert payload["agent_name"] == "test-agent"

    def test_custom_headers(self, webhook_server):
        backend = WebhookBackend(
            url=webhook_server,
            headers={"Authorization": "Bearer test-token", "X-Custom": "hello"},
        )
        backend.write(_make_event())

        req_headers = _RecordingHandler.received[0]["headers"]
        assert req_headers["Authorization"] == "Bearer test-token"
        assert req_headers["X-Custom"] == "hello"

    def test_batch_mode(self, webhook_server):
        backend = WebhookBackend(url=webhook_server, batch_size=3)

        backend.write(_make_event(event_id="e1"))
        backend.write(_make_event(event_id="e2"))
        assert len(_RecordingHandler.received) == 0

        backend.write(_make_event(event_id="e3"))
        assert len(_RecordingHandler.received) == 1
        payload = _RecordingHandler.received[0]["body"]
        assert isinstance(payload, list)
        assert len(payload) == 3

    def test_flush_sends_partial_batch(self, webhook_server):
        backend = WebhookBackend(url=webhook_server, batch_size=10)
        backend.write(_make_event())
        backend.write(_make_event())
        assert len(_RecordingHandler.received) == 0

        backend.flush()
        assert len(_RecordingHandler.received) == 1
        payload = _RecordingHandler.received[0]["body"]
        assert isinstance(payload, list)
        assert len(payload) == 2

    def test_close_flushes(self, webhook_server):
        backend = WebhookBackend(url=webhook_server, batch_size=100)
        backend.write(_make_event())
        backend.close()
        assert len(_RecordingHandler.received) == 1

    def test_stats_tracking(self, webhook_server):
        backend = WebhookBackend(url=webhook_server)
        backend.write(_make_event())
        backend.write(_make_event())

        stats = backend.get_stats()
        assert stats["event_count"] == 2
        assert stats["bytes_written"] > 0
        assert stats["backend_type"] == "webhook"
        assert stats["oldest_event_ts"] is not None
        assert stats["newest_event_ts"] is not None

    def test_failed_post_increments_error_count(self):
        backend = WebhookBackend(url="http://example.com/nope")
        with patch("urllib.request.urlopen", side_effect=Exception("mock network error")):
            backend.write(_make_event())

        stats = backend.get_stats()
        assert stats["event_count"] == 0
        assert backend._stats["events_failed"] == 1

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="non-empty url"):
            WebhookBackend(url="")

    def test_invalid_url_scheme_raises(self):
        with pytest.raises(ValueError, match="must start with 'http://' or 'https://'"):
            WebhookBackend(url="example.com/webhook")

    def test_non_positive_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout must be positive"):
            WebhookBackend(url="http://example.com", timeout=0)

    def test_content_type_header(self, webhook_server):
        backend = WebhookBackend(url=webhook_server)
        backend.write(_make_event())

        req_headers = _RecordingHandler.received[0]["headers"]
        assert req_headers["Content-Type"] == "application/json"
