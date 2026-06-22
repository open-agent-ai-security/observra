"""Hot/cold path event type classification for selective redaction.

Hot path: Safe metrics-only events with no user content (no redaction needed)
Cold path: Events that may contain PII/credentials in data field (requires redaction)
"""

# Hot path events: safe metrics-only, no user content
# These events contain only structured metadata (timestamps, counts, model names, etc.)
HOT_PATH_EVENT_TYPES = frozenset(
    [
        "session_start",
        "session_end",
        "agent_start",
        "agent_end",
        "model_request",
        "turn_duration",
        "cost_threshold_exceeded",
    ]
)
# NOTE: model_response is intentionally NOT hot path — Claude adapter's wrap_stream()
# includes response_text (a string) that would be stripped by hot path processing.

# Cold path events: may contain PII/credentials in data field
# These events can include user messages, error details, tool data, arbitrary payloads
COLD_PATH_EVENT_TYPES = frozenset(
    [
        "tool_start",  # May contain tool_args when capture_tool_data is enabled
        "tool_end",  # May contain tool_args and tool_result when capture_tool_data is enabled
        "tool_error",  # Contains error details for failed tool invocations
        "user_message",
        "model_error",
        "stream_event",  # Generic streaming event from on_event callback
        "adapter_close",
        "depth_exceeded",  # Contains agent name and message string, needs redaction
        "log_message",  # Log messages may contain PII or sensitive data
        "agent_handoff",  # Contains source_agent and target_agent string names
        "agent_handoff_error",  # Contains error details for failed handoff transfers
        # MCP proxy server tool call events — contain tool inputs/outputs (PII risk)
        "skill_invocation",
        # MCP session lifecycle — kept cold so mcp_agent_id, mcp_session_id, source survive
        "mcp_session_start",
        "mcp_session_end",
    ]
)


# CIM-vocabulary string keys that are always safe on hot path.
# These carry enumerated values (vendor=anthropic, action=call_llm, result=success)
# that are classification metadata, never PII. Hot-path nullification would erase
# the CIM alignment that downstream SIEM parsers rely on, so we pass them through.
HOT_PATH_SAFE_STRING_KEYS = frozenset(
    [
        "vendor",
        "action",
        "result",
        "exit_status",
        "ai_session_type",
        "risk_tier",
        "finish_reason",
        "role",
        "user_type",
        "data_classification",
        "max_severity",
        "atlas_technique_id",
        "policy_name",
        "channel",
        "kind",
        "dest_host",
        "session_key",
        "run_id",
        "log_source_type",  # product identifier, always safe (classification metadata)
    ]
)


def is_hot_path(event_type: str) -> bool:
    """Check if event type is on the hot path (safe, no redaction needed).

    Args:
        event_type: Event type string

    Returns:
        True if event is hot path (metrics-only)
    """
    return event_type in HOT_PATH_EVENT_TYPES


def is_cold_path(event_type: str) -> bool:
    """Check if event type is on the cold path (may need redaction).

    Args:
        event_type: Event type string

    Returns:
        True if event is cold path (may contain PII/credentials)
    """
    return event_type in COLD_PATH_EVENT_TYPES


def classify(event_type: str) -> str:
    """Classify an event type as 'hot' or 'cold' path.

    Unknown event types default to 'cold' (safer default — assumes PII risk).

    Args:
        event_type: Event type string

    Returns:
        'hot' if event is on the hot path (safe, no redaction needed)
        'cold' if event is on the cold path or unrecognized (may contain PII)
    """
    return "hot" if is_hot_path(event_type) else "cold"
