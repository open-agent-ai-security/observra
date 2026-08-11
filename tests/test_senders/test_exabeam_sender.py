# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for ExabeamSenderBackend — HTTPS webhook delivery to Exabeam SIEM.

Covers all ACs from Story 3.1:
  AC#1: env var validation, TLS enforcement, API key safety
  AC#2: correct POST call signature (URL, headers, timeout, verify)
  AC#3: injection_detected boolean, tool_inputs/tool_outputs absent
  AC#4: failure isolation — exceptions never re-raised
  AC#5: StorageBackend Protocol conformance, MultiBackend composition
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from observra.core.context import initialize_session, initialize_trace
from observra.core.events import create_event


def _make_env(
    endpoint: str = "https://collector.exabeam.example.com/api/v1/events",
    api_key: str = "test-api-key-secret",
    payload_mode: str = "json",
    field_overrides: dict | None = None,
) -> dict:
    env = {
        "EXABEAM_ENDPOINT": endpoint,
        "EXABEAM_API_KEY": api_key,
        "EXABEAM_PAYLOAD_MODE": payload_mode,
    }
    if field_overrides:
        for canonical, override in field_overrides.items():
            env["EXABEAM_FIELD_%s" % canonical.upper()] = override
    return env


def make_test_event(event_type: str = "skill_invocation", **kwargs):
    initialize_trace()
    initialize_session("test-session")
    return create_event(
        event_type,
        framework="mcp",
        skill_name="read_file",
        mcp_agent_id="claude/3.5-sonnet",
        mcp_session_id="sess-123",
        injection_patterns=kwargs.pop("injection_patterns", []),
        has_injection_patterns=kwargs.pop("has_injection_patterns", False),
        tool_velocity=1.0,
        tool_sequence=["read_file"],
        suspicious_sequence=False,
        delegation_depth=0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Story 3.2 — Raw payload mode (AC#1–#5)
# ---------------------------------------------------------------------------


class TestRawPayloadMode:
    def test_default_mode_uses_structured_payload(self):
        """AC#2: EXABEAM_PAYLOAD_MODE unset → structured build_payload() path."""
        with patch.dict(os.environ, _make_env(), clear=False):
            os.environ.pop("EXABEAM_PAYLOAD_MODE", None)
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp):
            with patch.object(backend, "build_payload", wraps=backend.build_payload) as spy_structured:
                with patch.object(backend, "build_raw_payload", wraps=backend.build_raw_payload) as spy_raw:
                    backend.write(make_test_event())

        spy_structured.assert_called_once()
        spy_raw.assert_not_called()

    def test_json_mode_uses_structured_payload(self):
        """AC#2: EXABEAM_PAYLOAD_MODE=json → structured build_payload() path."""
        with patch.dict(os.environ, _make_env(payload_mode="json")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp):
            with patch.object(backend, "build_payload", wraps=backend.build_payload) as spy_structured:
                with patch.object(backend, "build_raw_payload", wraps=backend.build_raw_payload) as spy_raw:
                    backend.write(make_test_event())

        spy_structured.assert_called_once()
        spy_raw.assert_not_called()

    def test_raw_mode_calls_build_raw_payload(self):
        """AC#1: EXABEAM_PAYLOAD_MODE=raw → build_raw_payload() called, not build_payload()."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        event = make_test_event(tool_inputs={"path": "/etc/passwd"}, tool_outputs="file content")

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp) as mock_post:
            backend.write(event)

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", {})
        assert "tool_inputs" in payload
        assert "tool_outputs" in payload
        assert "data" not in payload
        assert "injection_detected" in payload
        assert isinstance(payload["injection_detected"], bool)

    def test_raw_payload_includes_tool_inputs(self):
        """AC#4: raw payload includes tool_inputs (excluded in structured mode)."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(tool_inputs={"path": "/secret"})
        payload = backend.build_raw_payload(event)
        assert "tool_inputs" in payload

    def test_raw_payload_includes_tool_outputs(self):
        """AC#4: raw payload includes tool_outputs (excluded in structured mode)."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(tool_outputs="sensitive content")
        payload = backend.build_raw_payload(event)
        assert "tool_outputs" in payload

    def test_raw_payload_inlines_data_at_top_level(self):
        """AC#4: event.data fields are inlined at top level — no nested 'data' key."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(
            injection_patterns=["PROMPT_INJECTION"],
            has_injection_patterns=True,
        )
        payload = backend.build_raw_payload(event)
        assert "data" not in payload
        assert "injection_patterns" in payload

    def test_raw_payload_has_injection_detected_as_top_level_bool(self):
        """AC#4: injection_detected always present as top-level boolean in raw mode."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(injection_patterns=["OVERRIDE"], has_injection_patterns=True)
        payload = backend.build_raw_payload(event)
        assert "injection_detected" in payload
        assert payload["injection_detected"] is True
        assert isinstance(payload["injection_detected"], bool)

    def test_raw_payload_injection_detected_false_when_no_patterns(self):
        """AC#4: injection_detected is False when no injection_patterns."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(injection_patterns=[], has_injection_patterns=False)
        payload = backend.build_raw_payload(event)
        assert payload["injection_detected"] is False

    def test_raw_payload_timestamp_is_iso8601(self):
        """AC#4: timestamp in raw payload is ISO 8601 string."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event()
        payload = backend.build_raw_payload(event)
        from datetime import datetime

        dt = datetime.fromisoformat(payload["time"])
        assert dt.tzinfo is not None

    def test_raw_payload_handles_none_data(self):
        """AC#4: event.data being None is handled gracefully — no KeyError or TypeError."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        # Manually construct event with data=None to test the None path
        initialize_trace()
        initialize_session("test-session")
        event = create_event("model_response", framework="mcp")
        from dataclasses import replace as dc_replace

        event = dc_replace(event, data=None)
        payload = backend.build_raw_payload(event)
        assert payload["injection_detected"] is False
        assert "time" in payload

    def test_raw_mode_write_increments_count_on_success(self):
        """AC#2: _write_count incremented on HTTP 2xx success in raw mode."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp):
            backend.write(make_test_event())
            backend.write(make_test_event())

        assert backend._write_count == 2

    def test_raw_mode_failure_isolation(self):
        """AC#5: ConnectionError in raw mode is caught, logged, not re-raised."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        with patch(
            "observra.senders.exabeam.requests.post",
            side_effect=ConnectionError("refused"),
        ):
            backend.write(make_test_event())  # must NOT raise

    def test_raw_mode_failure_logs_warning(self, caplog):
        """AC#5: failure in raw mode logs warning."""
        import logging

        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        with patch(
            "observra.senders.exabeam.requests.post",
            side_effect=ConnectionError("refused"),
        ):
            with caplog.at_level(logging.WARNING, logger="observra.senders.exabeam"):
                backend.write(make_test_event())

        assert any("Exabeam webhook delivery failed" in r.message for r in caplog.records)

    def test_repr_includes_payload_mode_raw(self):
        """__repr__() includes payload_mode=raw when in raw mode."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        r = repr(backend)
        assert "payload_mode=raw" in r

    def test_repr_includes_payload_mode_json(self):
        """__repr__() includes payload_mode=json when in json mode."""
        with patch.dict(os.environ, _make_env(payload_mode="json")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        r = repr(backend)
        assert "payload_mode=json" in r


# ---------------------------------------------------------------------------
# Story 3.3 — Field name configurability (AC#1–#3)
# ---------------------------------------------------------------------------


class TestFieldNameConfigurability:
    def test_field_override_injection_detected(self):
        """AC#1: EXABEAM_FIELD_INJECTION_DETECTED=ai_injection_flag → key is remapped."""
        env = _make_env(field_overrides={"injection_detected": "ai_injection_flag"})
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(
            injection_patterns=["PROMPT_INJECTION"],
            has_injection_patterns=True,
        )
        payload = backend.build_payload(event)
        assert "ai_injection_flag" in payload
        assert "injection_detected" not in payload
        assert payload["ai_injection_flag"] is True

    def test_multiple_field_overrides_applied_simultaneously(self):
        """AC#1: Multiple overrides applied in same payload."""
        env = _make_env(
            field_overrides={
                "event_type": "activity_type",
                "agent_name": "actor",
            }
        )
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event()
        payload = backend.build_payload(event)
        assert "activity_type" in payload
        assert "actor" in payload
        assert "event_type" not in payload
        assert "agent_name" not in payload

    def test_no_overrides_uses_canonical_names(self):
        """AC#2: No EXABEAM_FIELD_* set → canonical names, field_map empty."""
        env = _make_env()
        with patch.dict(os.environ, env, clear=False):
            # Ensure no EXABEAM_FIELD_* vars leak in
            for k in list(os.environ.keys()):
                if k.startswith("EXABEAM_FIELD_"):
                    del os.environ[k]
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        assert backend._field_map == {}
        event = make_test_event()
        payload = backend.build_payload(event)
        assert "injection_detected" in payload
        assert "event_type" in payload
        assert "agent_name" in payload

    def test_unknown_field_override_warns_and_is_ignored(self, caplog):
        """AC#3: Unknown EXABEAM_FIELD_* override → warning logged, backend starts, override ignored."""
        import logging

        env = _make_env(field_overrides={"unknown_field": "foo"})
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            with caplog.at_level(logging.WARNING, logger="observra.senders.exabeam"):
                backend = ExabeamSenderBackend()

        assert any("UNKNOWN_FIELD" in r.message for r in caplog.records)
        event = make_test_event()
        payload = backend.build_payload(event)
        assert "foo" not in payload.values()
        assert "unknown_field" not in payload

    def test_mix_of_valid_and_invalid_overrides(self, caplog):
        """AC#3: Valid overrides applied, invalid ones warned and ignored."""
        import logging

        env = _make_env(
            field_overrides={
                "injection_detected": "ai_injection_flag",
                "unknown_field": "foo",
            }
        )
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            with caplog.at_level(logging.WARNING, logger="observra.senders.exabeam"):
                backend = ExabeamSenderBackend()

        assert any("UNKNOWN_FIELD" in r.message for r in caplog.records)
        event = make_test_event(injection_patterns=["X"], has_injection_patterns=True)
        payload = backend.build_payload(event)
        assert "ai_injection_flag" in payload
        assert "injection_detected" not in payload
        assert "foo" not in payload.values()

    def test_field_override_does_not_affect_raw_mode(self):
        """AC#1: Raw mode bypasses field map — canonical names used in raw payload."""
        env = _make_env(
            payload_mode="raw",
            field_overrides={"injection_detected": "ai_injection_flag"},
        )
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(injection_patterns=["X"], has_injection_patterns=True)
        payload = backend.build_raw_payload(event)
        assert "injection_detected" in payload
        assert "ai_injection_flag" not in payload

    def test_repr_includes_field_overrides_count_when_active(self):
        """AC#1/#2: __repr__() includes field_overrides=1 when one override is active."""
        env = _make_env(field_overrides={"injection_detected": "ai_injection_flag"})
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        r = repr(backend)
        assert "field_overrides=1" in r

    def test_repr_excludes_field_overrides_when_none_set(self):
        """AC#2: __repr__() does NOT include field_overrides when no overrides set."""
        env = _make_env()
        with patch.dict(os.environ, env, clear=False):
            for k in list(os.environ.keys()):
                if k.startswith("EXABEAM_FIELD_"):
                    del os.environ[k]
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        r = repr(backend)
        assert "field_overrides" not in r


# ---------------------------------------------------------------------------
# AC#1 — Env var validation and TLS enforcement
# ---------------------------------------------------------------------------


class TestInitValidation:
    def test_missing_endpoint_raises(self):
        env = {"EXABEAM_API_KEY": "key"}
        with patch.dict(os.environ, env, clear=True):
            # Remove EXABEAM_ENDPOINT if present
            os.environ.pop("EXABEAM_ENDPOINT", None)
            from observra.senders.exabeam import ExabeamSenderBackend

            with pytest.raises(ValueError, match="EXABEAM_ENDPOINT environment variable not set"):
                ExabeamSenderBackend()

    def test_http_endpoint_raises_at_init(self):
        env = _make_env(endpoint="http://collector.exabeam.example.com/api/v1/events")
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            with pytest.raises(ValueError, match="EXABEAM_ENDPOINT must use HTTPS"):
                ExabeamSenderBackend()

    def test_missing_api_key_raises(self):
        env = {"EXABEAM_ENDPOINT": "https://collector.exabeam.example.com/api/v1/events"}
        with patch.dict(os.environ, env, clear=True):
            os.environ.pop("EXABEAM_API_KEY", None)
            from observra.senders.exabeam import ExabeamSenderBackend

            with pytest.raises(ValueError, match="EXABEAM_API_KEY environment variable not set"):
                ExabeamSenderBackend()

    def test_api_key_not_in_repr(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()
        r = repr(backend)
        assert "test-api-key-secret" not in r
        assert "<redacted>" in r

    def test_valid_init_succeeds(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()
        assert backend is not None

    def test_invalid_payload_mode_raises_at_init(self):
        """AC#3: invalid EXABEAM_PAYLOAD_MODE raises ValueError at init, not at delivery."""
        env = _make_env(payload_mode="xml")
        with patch.dict(os.environ, env):
            from observra.senders.exabeam import ExabeamSenderBackend

            with pytest.raises(ValueError, match="EXABEAM_PAYLOAD_MODE must be 'json' or 'raw'"):
                ExabeamSenderBackend()

    def test_valid_raw_payload_mode_init_succeeds(self):
        """AC#1: EXABEAM_PAYLOAD_MODE=raw is a valid value at init."""
        with patch.dict(os.environ, _make_env(payload_mode="raw")):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()
        assert backend is not None


# ---------------------------------------------------------------------------
# AC#2 — POST call signature
# ---------------------------------------------------------------------------


class TestWritePostSignature:
    def test_write_posts_to_endpoint(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp) as mock_post:
            backend.write(make_test_event())

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("timeout") == 5.0
        assert call_kwargs.kwargs.get("verify") is True
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_write_posts_to_correct_url(self):
        endpoint = "https://collector.exabeam.example.com/api/v1/events"
        with patch.dict(os.environ, _make_env(endpoint=endpoint)):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp) as mock_post:
            backend.write(make_test_event())

        assert mock_post.call_args.args[0] == endpoint

    def test_write_increments_count_on_success(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp):
            backend.write(make_test_event())
            backend.write(make_test_event())

        assert backend._write_count == 2


# ---------------------------------------------------------------------------
# AC#3 — injection_detected boolean, tool_inputs/tool_outputs absent
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_injection_detected_true_when_patterns_present(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(
            injection_patterns=["INSTRUCTION_OVERRIDE"],
            has_injection_patterns=True,
        )
        payload = backend.build_payload(event)
        assert payload["injection_detected"] is True

    def test_injection_detected_false_when_no_patterns(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(injection_patterns=[], has_injection_patterns=False)
        payload = backend.build_payload(event)
        assert payload["injection_detected"] is False

    def test_injection_detected_false_when_patterns_absent(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        # event with None data
        initialize_trace()
        initialize_session("test-session")
        event = create_event("model_response", framework="mcp")
        payload = backend.build_payload(event)
        assert payload["injection_detected"] is False

    def test_tool_inputs_absent_from_payload(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(tool_inputs={"path": "/secret"})
        payload = backend.build_payload(event)
        assert "tool_inputs" not in payload

    def test_tool_outputs_absent_from_payload(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(tool_outputs="sensitive content")
        payload = backend.build_payload(event)
        assert "tool_outputs" not in payload

    def test_payload_contains_required_fields(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event()
        payload = backend.build_payload(event)

        required = [
            "time",
            "event_id",
            "event_type",
            "framework",
            "session_id",
            "trace_id",
            "span_id",
            "injection_detected",
        ]
        for field in required:
            assert field in payload, f"Missing required field: {field}"

    def test_error_type_and_retryable_fields_in_payload(self):
        """H2: error_type_name and is_retryable (canonical schema names) appear in payload."""
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event(error_type_name="ConnectionError", is_retryable=True)
        payload = backend.build_payload(event)
        assert "error_type_name" in payload
        assert "is_retryable" in payload
        assert payload["error_type_name"] == "ConnectionError"
        assert payload["is_retryable"] is True
        # Ensure old wrong names are NOT used
        assert "error_type" not in payload
        assert "error_retryable" not in payload

    def test_payload_time_is_iso8601(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        event = make_test_event()
        payload = backend.build_payload(event)
        # Should parse as ISO 8601 without error
        from datetime import datetime

        dt = datetime.fromisoformat(payload["time"])
        assert dt.tzinfo is not None  # must include timezone


# ---------------------------------------------------------------------------
# AC#4 — Failure isolation — exceptions never re-raised
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    def test_connection_error_does_not_raise(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        with patch(
            "observra.senders.exabeam.requests.post",
            side_effect=ConnectionError("refused"),
        ):
            backend.write(make_test_event())  # must NOT raise

    def test_timeout_error_does_not_raise(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        with patch(
            "observra.senders.exabeam.requests.post",
            side_effect=TimeoutError("timed out"),
        ):
            backend.write(make_test_event())  # must NOT raise

    def test_non_2xx_does_not_raise(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 not found")

        with patch("observra.senders.exabeam.requests.post", return_value=mock_resp):
            backend.write(make_test_event())  # must NOT raise

    def test_failure_logs_warning(self, caplog):
        import logging

        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        with patch(
            "observra.senders.exabeam.requests.post",
            side_effect=ConnectionError("refused"),
        ):
            with caplog.at_level(logging.WARNING, logger="observra.senders.exabeam"):
                backend.write(make_test_event())

        assert any("Exabeam webhook delivery failed" in r.message for r in caplog.records)

    def test_failure_does_not_increment_write_count(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        with patch(
            "observra.senders.exabeam.requests.post",
            side_effect=ConnectionError("refused"),
        ):
            backend.write(make_test_event())

        assert backend._write_count == 0


# ---------------------------------------------------------------------------
# AC#5 — StorageBackend Protocol conformance and MultiBackend composition
# ---------------------------------------------------------------------------


class TestStorageBackendProtocol:
    def test_satisfies_storage_backend_protocol(self):
        from observra.core.storage import StorageBackend

        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()
        assert isinstance(backend, StorageBackend)

    def test_get_stats_returns_backend_stats(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        stats = backend.get_stats()
        assert stats["backend_type"] == "exabeam"
        assert stats["bytes_written"] == 0
        assert stats["event_count"] == 0
        assert stats["oldest_event_ts"] is None
        assert stats["newest_event_ts"] is None

    def test_flush_is_noop(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()
        backend.flush()  # must not raise

    def test_close_is_noop(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()
        backend.close()  # must not raise

    def test_query_raises_not_implemented(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            backend = ExabeamSenderBackend()

        with pytest.raises(NotImplementedError, match="ExabeamSenderBackend does not support query"):
            list(backend.query())

    def test_multibackend_exabeam_failure_does_not_block_jsonl(self, tmp_path):
        """Exabeam failure in MultiBackend must not prevent JSONLBackend from writing."""
        import json

        from observra.backends.jsonl import JSONLBackend
        from observra.backends.multi import MultiBackend

        jsonl_path = tmp_path / "telemetry.jsonl"
        jsonl_backend = JSONLBackend(path=str(jsonl_path))

        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            exabeam_backend = ExabeamSenderBackend()

        multi = MultiBackend([exabeam_backend, jsonl_backend])
        event = make_test_event()

        # Exabeam POST always fails
        with patch(
            "observra.senders.exabeam.requests.post",
            side_effect=ConnectionError("refused"),
        ):
            multi.write(event)
            multi.flush()

        jsonl_backend.close()

        # JSONLBackend should still have written the event to disk
        assert jsonl_path.exists(), "JSONL file should exist after write"
        lines = jsonl_path.read_text().strip().splitlines()
        assert len(lines) == 1, "Should have exactly 1 event written"
        written = json.loads(lines[0])
        assert written["event_id"] == event.event_id


# ---------------------------------------------------------------------------
# Parser match condition conformance tests
# ---------------------------------------------------------------------------


class TestParserMatchConditions:
    """Verify payloads satisfy all three Exabeam parser match conditions."""

    def _get_backend(self):
        with patch.dict(os.environ, _make_env()):
            from observra.senders.exabeam import ExabeamSenderBackend

            return ExabeamSenderBackend()

    def test_build_payload_has_schema(self):
        backend = self._get_backend()
        payload = backend.build_payload(make_test_event())
        assert payload["schema"] == "observra:1.0"

    def test_build_payload_has_type(self):
        backend = self._get_backend()
        payload = backend.build_payload(make_test_event())
        assert payload["type"] == "skill_invocation"

    def test_build_payload_has_framework(self):
        backend = self._get_backend()
        payload = backend.build_payload(make_test_event())
        assert payload["framework"] == "mcp"

    def test_build_payload_all_three_conditions(self):
        """All three parser match conditions present in a single payload."""
        backend = self._get_backend()
        payload = backend.build_payload(make_test_event())
        assert '"schema"' not in str(payload) or payload.get("schema", "").startswith("observra")
        assert "type" in payload
        assert "framework" in payload
        assert "schema" in payload

    def test_build_raw_payload_has_schema(self):
        backend = self._get_backend()
        payload = backend.build_raw_payload(make_test_event())
        assert payload["schema"] == "observra:1.0"

    def test_build_raw_payload_has_type(self):
        backend = self._get_backend()
        payload = backend.build_raw_payload(make_test_event())
        assert payload["type"] == "skill_invocation"

    def test_build_raw_payload_has_framework(self):
        backend = self._get_backend()
        payload = backend.build_raw_payload(make_test_event())
        assert payload["framework"] == "mcp"

    def test_event_type_still_present_for_backward_compat(self):
        """event_type kept alongside type for consumers using the old key."""
        backend = self._get_backend()
        payload = backend.build_payload(make_test_event())
        assert payload["event_type"] == "skill_invocation"
        assert payload["type"] == "skill_invocation"
