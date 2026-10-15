# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Serialize a TelemetryEvent in the agent-sensor wire format.

agent-sensor's ``SimplifiedEvent`` (aba-sensor ``src/types.rs``) is the record
shape the Exabeam parser is written against. Emitting the same shape lets one
parser handle both the endpoint sensor and this SDK. Field order and names
mirror ``SimplifiedEvent``; ``None`` fields are omitted, as serde does there.

``device_id`` is the one top-level field ahead of the sensor; agent-sensor
should add it next to ``host`` with the same derivation (host_context.py).

Fields the sensor has no slot for (``event_id``, ``trace_id``, ``span_id``,
``skill_name``) and the full session id (``session_key``) go under ``data``.
"""

from datetime import datetime, timezone
from typing import Any

from .cim import CIM_VERSION, PRODUCT_ID
from .events import TelemetryEvent
from .hot_cold import HOT_PATH_SAFE_STRING_KEYS

# Sensor top-level field -> data keys it is read from, first non-None wins.
# Adapters name some fields differently, hence several sources per field.
_PROMOTED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prompt", ("prompt_text",)),
    ("response", ("response_text",)),
    ("text", ("user_message_text", "text")),
    ("error", ("error_message", "error_type_name")),
    ("stop", ("stop_reason", "finish_reason")),
    ("in", ("input_tokens",)),
    ("out", ("output_tokens",)),
    ("cache_read", ("cached_tokens", "cache_read_tokens", "cache_read_input_tokens")),
    ("cache_creation", ("cache_creation_tokens", "cache_creation_input_tokens")),
    ("duration_ms", ("duration_ms",)),
    ("messages", ("messages", "message_count")),
    ("cost_usd", ("cost_usd",)),
    ("has_injection", ("has_injection_patterns",)),
    ("injection_patterns", ("injection_patterns",)),
    ("suspicious_sequence", ("suspicious_sequence",)),
    ("error_class", ("error_class",)),
    ("is_retryable", ("is_retryable",)),
    ("triggered_rules", ("triggered_rules",)),
    ("max_severity", ("max_severity",)),
)

# Free-text fields dropped when content capture is off.
_CONTENT_FIELDS = frozenset({"prompt", "response", "text"})

# Native-only field the sensor's schema tests ban from serialized output.
_BANNED_DATA_KEYS = frozenset({"log_source_type"})


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        val = data.get(key)
        if val is not None:
            return val
    return None


def to_sensor_record(event: TelemetryEvent, include_content: bool = True) -> dict[str, Any]:
    """Return ``event`` as an agent-sensor ``SimplifiedEvent``-shaped dict.

    Args:
        event: The event to serialize.
        include_content: When False, drop prompt/response/text and every
            free-text ``data`` value except CIM vocabulary keys. Used by
            backends that promise a PII-free body (OTel logs).
    """
    data = event.data or {}

    rec: dict[str, Any] = {
        "ts": datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat(timespec="microseconds"),
        "session": event.session_id[:8],
        "type": event.event_type,
        "model": event.model_name,
        "tool": event.tool_name,
        "agent": event.agent_name,
    }
    for field, keys in _PROMOTED:
        rec[field] = _first(data, keys)

    if not rec["triggered_rules"]:
        rec["triggered_rules"] = None  # sensor skips an empty list
    if not include_content:
        for field in _CONTENT_FIELDS:
            rec[field] = None

    out_data = {
        k: v
        for k, v in data.items()
        if v is not None
        and k not in _BANNED_DATA_KEYS
        and (include_content or not isinstance(v, str) or k in HOT_PATH_SAFE_STRING_KEYS)
    }
    out_data["session_key"] = event.session_id
    out_data["event_id"] = event.event_id
    out_data["trace_id"] = event.trace_id
    out_data["span_id"] = event.span_id
    if event.skill_name:
        out_data["skill_name"] = event.skill_name
    rec["data"] = out_data

    rec["framework"] = event.framework
    rec["host"] = event.host
    rec["user"] = event.user
    rec["os"] = event.os
    rec["arch"] = event.arch
    rec["device_id"] = event.device_id
    rec["forwarder"] = f"{PRODUCT_ID}:{event.library_version}" if event.library_version else None
    rec["schema"] = f"{PRODUCT_ID}:{CIM_VERSION}"

    return {k: v for k, v in rec.items() if v is not None}
