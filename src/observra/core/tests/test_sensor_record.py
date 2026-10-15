# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Records must carry agent-sensor's SimplifiedEvent field names, so one parser reads both."""

import json

from observra.backends.jsonl import JSONLBackend
from observra.core.events import create_event
from observra.core.sensor_record import to_sensor_record

# Serialized field names of SimplifiedEvent (aba-sensor src/types.rs).
SENSOR_FIELDS = {
    "ts", "session", "type", "model", "prompt", "response", "text", "tool", "agent",
    "error", "stop", "in", "out", "cache_read", "cache_creation", "duration_ms",
    "messages", "cost_usd", "has_injection", "injection_patterns", "suspicious_sequence",
    "error_class", "is_retryable", "triggered_rules", "max_severity", "data",
    "framework", "host", "user", "os", "arch", "forwarder", "schema",
    "device_id",  # proposed for SimplifiedEvent; observra emits it first
}  # fmt: skip


def _full_event():
    return create_event(
        "model_response",
        model_name="claude-sonnet-4-6",
        agent_name="advisor",
        tool_name="bash",
        framework="claude",
        prompt_text="hi",
        response_text="hello",
        user_message_text="hi",
        error_message="boom",
        stop_reason="end_turn",
        input_tokens=10,
        output_tokens=20,
        cached_tokens=30,
        cache_creation_tokens=40,
        duration_ms=1.5,
        messages=3,
        cost_usd=0.01,
        has_injection_patterns=True,
        injection_patterns=["JAILBREAK_DAN"],
        suspicious_sequence=True,
        error_class="network",
        is_retryable=True,
        tool_use_id="toolu_1",
    )


def test_every_field_maps_to_a_sensor_field():
    rec = to_sensor_record(_full_event())
    assert set(rec) - SENSOR_FIELDS == set()
    # Everything the event supplied is promoted, so only fields no adapter can set are absent.
    # device_id is None on hosts with no machine id (e.g. minimal containers).
    assert SENSOR_FIELDS - set(rec) <= {"triggered_rules", "max_severity", "device_id"}


def test_values_and_data_block():
    ev = _full_event()
    rec = to_sensor_record(ev)
    assert rec["session"] == ev.session_id[:8]
    assert rec["type"] == "model_response"
    assert (rec["in"], rec["out"], rec["cache_read"], rec["cache_creation"]) == (10, 20, 30, 40)
    assert rec["has_injection"] is True
    assert rec["schema"] == "observra:1.1"
    assert rec["forwarder"] == f"observra:{ev.library_version}"
    d = rec["data"]
    assert (d["action"], d["vendor"], d["result"]) == ("call_llm", "anthropic", "success")
    assert d["session_key"] == ev.session_id
    assert (d["event_id"], d["trace_id"], d["span_id"]) == (ev.event_id, ev.trace_id, ev.span_id)
    assert d["tool_use_id"] == "toolu_1"
    assert "log_source_type" not in d
    assert None not in d.values()


def test_without_content_drops_free_text():
    rec = to_sensor_record(_full_event(), include_content=False)
    assert not {"prompt", "response", "text"} & set(rec)
    assert "hello" not in json.dumps(rec)
    assert rec["data"]["action"] == "call_llm"


def test_jsonl_writes_sensor_shape_by_default(tmp_path):
    path = tmp_path / "t.jsonl"
    backend = JSONLBackend(path=path)
    backend.write(create_event("tool_end", tool_name="bash", framework="claude", duration_ms=5))
    backend.close()
    rec = json.loads(path.read_text())
    assert set(rec) <= SENSOR_FIELDS
    assert rec["tool"] == "bash"


def test_ts_always_has_six_fraction_digits():
    # Parser TimeFormat is yyyy-MM-dd'T'HH:mm:ss.SSSSSSZ; isoformat() drops the fraction on whole seconds.
    from dataclasses import replace

    rec = to_sensor_record(replace(_full_event(), timestamp=1792100066.0))
    assert rec["ts"] == "2026-10-15T21:34:26.000000+00:00"


def test_role_defaults_match_sensor():
    assert to_sensor_record(create_event("user_message"))["data"]["role"] == "user"
    assert to_sensor_record(create_event("model_response"))["data"]["role"] == "assistant"
    assert "role" not in to_sensor_record(create_event("tool_end"))["data"]
