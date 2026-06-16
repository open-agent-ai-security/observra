"""Tests for OTelLogBackend body_schema parameter.

Covers:
  - Default "native" body schema (safe fields, library key names)
  - "sensor" body schema (short keys matching CLI JSONL writer / aba-sensor)
  - OTel attributes remain unchanged regardless of body_schema
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from aba_telemetry.core.events import create_event


@pytest.fixture
def captured_log_records(monkeypatch):
    """Capture OTel log records emitted by OTelLogBackend.write()."""
    records = []

    import aba_telemetry.backends.otel_log as otel_log_module

    class _CapturingLogger:
        def emit(self, log_record):
            records.append(log_record)

    class _CapturingProvider:
        def __init__(self, resource=None):
            self._logger = _CapturingLogger()

        def get_logger(self, *args, **kwargs):
            return self._logger

        def add_log_record_processor(self, processor):
            pass

        def force_flush(self, timeout_millis=None):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(otel_log_module, "LoggerProvider", _CapturingProvider)
    monkeypatch.setattr(
        otel_log_module,
        "OTLPLogExporter",
        lambda endpoint=None, headers=None, timeout=None: MagicMock(),
    )
    monkeypatch.setattr(
        otel_log_module,
        "BatchLogRecordProcessor",
        lambda exporter: MagicMock(),
    )

    return records


def _parse_body(records, index=0):
    """Parse the JSON body string from a captured log record."""
    return json.loads(records[index].body)


class TestNativeBodySchema:
    """Default body_schema='native' uses library field names."""

    def test_model_response_native_body(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="native")
        event = create_event(
            "model_response",
            model_name="gemini-2.5-flash",
            agent_name="advisor",
            framework="adk",
            input_tokens=150,
            output_tokens=42,
            cost_usd=0.003,
            stop_reason="end_turn",
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["event_type"] == "model_response"
        assert body["model_name"] == "gemini-2.5-flash"
        assert body["agent_name"] == "advisor"
        assert body["input_tokens"] == 150
        assert body["output_tokens"] == 42
        assert body["cost_usd"] == 0.003
        assert body["stop_reason"] == "end_turn"
        assert body["framework"] == "adk"

    def test_native_body_excludes_pii(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="native")
        event = create_event(
            "model_response",
            model_name="gpt-4o",
            framework="openai",
            prompt_text="secret password is hunter2",
            response_text="I see your password",
            tool_result="database row with SSN",
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert "prompt_text" not in body
        assert "response_text" not in body
        assert "tool_result" not in body
        assert "hunter2" not in json.dumps(body)


class TestSensorBodySchema:
    """body_schema='sensor' uses short keys matching CLI JSONL writer."""

    def test_model_response_preserves_type(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "model_response",
            model_name="gemini-2.5-flash",
            agent_name="advisor",
            framework="adk",
            input_tokens=150,
            output_tokens=42,
            cost_usd=0.003,
            stop_reason="end_turn",
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["type"] == "model_response"
        assert body["model"] == "gemini-2.5-flash"
        assert body["agent"] == "advisor"
        assert body["in"] == 150
        assert body["out"] == 42
        assert body["cost_usd"] == 0.003
        assert body["stop"] == "end_turn"
        assert body["framework"] == "adk"
        assert body["schema"] == "aba-telemetry"
        assert "ts" in body
        assert "session" in body
        assert len(body["session"]) == 8

    def test_tool_end_sensor_body(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "tool_end",
            tool_name="search_logs",
            framework="adk",
            duration_ms=245,
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["type"] == "tool_end"
        assert body["tool"] == "search_logs"
        assert body["duration_ms"] == 245

    def test_tool_error_sensor_body(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "tool_error",
            tool_name="fetch_data",
            framework="adk",
            error_type="TimeoutError",
            error_message="Connection timed out after 30s",
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["type"] == "tool_error"
        assert body["tool"] == "fetch_data"
        assert body["error"] == "Connection timed out after 30s"

    def test_sensor_body_excludes_pii(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "model_response",
            model_name="gpt-4o",
            framework="openai",
            prompt_text="secret password",
            response_text="echoed secret",
            tool_result="PII data",
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert "secret" not in json.dumps(body)
        assert "PII" not in json.dumps(body)

    def test_cache_token_keys(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "model_response",
            model_name="claude-sonnet-4-6",
            framework="claude",
            input_tokens=1,
            output_tokens=540,
            cache_read_tokens=18046,
            cache_creation_tokens=1256,
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["in"] == 1
        assert body["out"] == 540
        assert body["cache_read"] == 18046
        assert body["cache_creation"] == 1256

    def test_cached_tokens_maps_to_cache_read(self, captured_log_records):
        """cached_tokens (CIM standard field from ADK adapter) maps to cache_read."""
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "model_response",
            model_name="gemini-2.5-flash",
            framework="adk",
            input_tokens=100,
            output_tokens=50,
            cached_tokens=5000,
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["cache_read"] == 5000

    def test_session_id_truncated(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event("session_start", framework="adk")
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["type"] == "session_start"
        assert len(body["session"]) == 8


class TestInjectionDetection:
    """Injection detection metadata surfaces in both body schemas and attributes."""

    def test_injection_in_native_body(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="native")
        event = create_event(
            "user_message",
            framework="adk",
            has_injection_patterns=True,
            injection_patterns=["JAILBREAK_DAN", "INSTRUCTION_OVERRIDE"],
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["has_injection_patterns"] is True
        assert body["injection_patterns"] == ["JAILBREAK_DAN", "INSTRUCTION_OVERRIDE"]

    def test_injection_in_sensor_body(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "user_message",
            framework="adk",
            has_injection_patterns=True,
            injection_patterns=["BASE64_BLOB"],
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["injection"] is True
        assert body["injection_patterns"] == ["BASE64_BLOB"]

    def test_injection_in_attributes(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="native")
        event = create_event(
            "user_message",
            framework="adk",
            has_injection_patterns=True,
            injection_patterns=["SYSTEM_PROMPT_EXTRACTION", "JAILBREAK_ROLEPLAY"],
        )
        backend.write(event)

        attrs = captured_log_records[0].attributes
        assert attrs["aba_telemetry.has_injection_patterns"] is True
        assert attrs["aba_telemetry.injection_patterns"] == "SYSTEM_PROMPT_EXTRACTION,JAILBREAK_ROLEPLAY"

    def test_no_injection_omits_fields(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="native")
        event = create_event(
            "user_message",
            framework="adk",
            has_injection_patterns=False,
        )
        backend.write(event)

        body = _parse_body(captured_log_records)
        assert body["has_injection_patterns"] is False
        assert "injection_patterns" not in body

        attrs = captured_log_records[0].attributes
        assert attrs["aba_telemetry.has_injection_patterns"] is False
        assert "aba_telemetry.injection_patterns" not in attrs


class TestAttributesUnchanged:
    """OTel attributes stay gen_ai.* semconv regardless of body_schema."""

    def test_sensor_schema_does_not_change_attributes(self, captured_log_records):
        from aba_telemetry.backends.otel_log import OTelLogBackend

        backend = OTelLogBackend(body_schema="sensor")
        event = create_event(
            "model_response",
            model_name="gemini-2.5-flash",
            agent_name="advisor",
            framework="adk",
            input_tokens=100,
        )
        backend.write(event)

        attrs = captured_log_records[0].attributes
        assert attrs["gen_ai.request.model"] == "gemini-2.5-flash"
        assert attrs["gen_ai.agent.name"] == "advisor"
        assert attrs["gen_ai.usage.input_tokens"] == 100
        assert attrs["aba_telemetry.event_type"] == "model_response"
        assert attrs["aba_telemetry.framework"] == "adk"
