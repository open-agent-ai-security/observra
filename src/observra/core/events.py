"""Telemetry event schema and factory functions."""

import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from .context import get_trace_id, get_session_id, get_span_id
from .utils import generate_ulid, generate_timestamp
from .redaction import Redactor
from .hot_cold import is_hot_path, HOT_PATH_SAFE_STRING_KEYS
from .rules import evaluate_rules
from . import cim as _cim
from .host_context import get_host_context

logger = logging.getLogger(__name__)

# Canonical field defaults per event type.
# Every adapter MUST produce events with these keys in data — None when unavailable.
# This ensures uniform log schema regardless of framework capabilities.
_EVENT_SCHEMAS: dict[str, dict[str, Any]] = {
    # Core CIM fields — present in every framework's events for this type.
    # Framework-specific extras (ADK tool_sequence, OpenAI trigger_tool, etc.)
    # are NOT listed here; they flow through naturally as extra keys when that
    # framework sets them, without polluting other frameworks' logs with None noise.
    "model_response": {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cached_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
    },
    "model_error": {
        "error_message": None,
        "error_type_name": None,
        "is_retryable": None,
    },
    "tool_start": {
        "tool_args": None,
    },
    "tool_end": {
        "duration_ms": None,
        "tool_args": None,
        "tool_result": None,
    },
    "tool_error": {
        "error_message": None,
        "error_type_name": None,
        "is_retryable": None,
    },
    "session_end": {
        "error_message": None,
        "session_cost_usd": None,
    },
    "user_message": {
        "user_message_text": None,
    },
    "cost_threshold_exceeded": {
        "session_cost_usd": None,
        "threshold_usd": None,
        "exceeded": None,
        "message": None,
    },
    "agent_handoff": {
        "source_agent": None,
        "target_agent": None,
    },
    "agent_handoff_error": {
        "source_agent": None,
        "target_agent": None,
        "error_message": None,
    },
    "turn_duration": {
        "duration_ms": None,
    },
    "depth_exceeded": {
        "current_depth": None,
        "max_depth": None,
        "message": None,
    },
    # MCP proxy server events (observra/mcp/)
    "skill_invocation": {
        "mcp_agent_id": None,
        "mcp_session_id": None,
        "tool_inputs": None,
        "tool_outputs": None,
        "injection_patterns": None,
        "has_injection_patterns": None,
        "tool_velocity": None,       # float: calls/min from velocity.py sliding window
        "tool_sequence": None,       # list[str]: tool names in session order
        "suspicious_sequence": None, # bool: matches suspicious pattern (sequences.py)
        "delegation_depth": None,    # int: 0 for top-level, N for subagent (Story 2.3)
        # NOTE: error_type and error_retryable intentionally NOT in schema
        # They appear ONLY for error events (must be absent, not None, on success)
    },
}


class EventType:
    """Canonical event type constants for cross-framework telemetry.

    All adapters MUST use these constants so that queries like
    ``WHERE event_type = 'tool_end'`` work identically regardless of
    which framework generated the event.
    """

    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Agent lifecycle
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"

    # Model lifecycle
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    MODEL_ERROR = "model_error"
    TURN_DURATION = "turn_duration"

    # Tool lifecycle
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"

    # User interaction
    USER_MESSAGE = "user_message"

    # Cost / safety
    COST_THRESHOLD_EXCEEDED = "cost_threshold_exceeded"
    DEPTH_EXCEEDED = "depth_exceeded"

    # Agent-to-agent (OpenAI)
    AGENT_HANDOFF = "agent_handoff"
    AGENT_HANDOFF_ERROR = "agent_handoff_error"

    # Streaming / adapter lifecycle
    STREAM_EVENT = "stream_event"
    ADAPTER_CLOSE = "adapter_close"

    # MCP proxy server (observra/mcp/) — FastMCP transparent proxy events
    SKILL_INVOCATION = "skill_invocation"    # Tool call intercepted by proxy (cold path)
    MCP_SESSION_START = "mcp_session_start"  # MCP client connected (hot path)
    MCP_SESSION_END = "mcp_session_end"      # MCP client disconnected (hot path)


# Framework name type alias
FrameworkName = Literal["adk", "claude", "claude_code", "codex_cli", "codex_app", "gemini_cli", "openai", "langgraph", "pydantic-ai", "copilot", "mcp", "openclaw", "unknown"]

# Module-level redactor singleton (configured via initialize())
_redactor: Redactor = Redactor()


def configure_redactor(custom_patterns: list[tuple[str, str]] | None = None) -> None:
    """Configure the module-level redactor with custom patterns.

    Called by initialize() to set up custom redaction patterns.
    Must be called before any events are created if custom patterns needed.

    Args:
        custom_patterns: Optional list of (regex_pattern, marker_name) tuples.
    """
    global _redactor
    _redactor = Redactor(custom_patterns=custom_patterns)


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    """Immutable telemetry event with required tracing fields.

    Required fields:
        event_id: Unique event identifier (ULID)
        timestamp: Unix timestamp
        trace_id: Distributed trace identifier
        session_id: Session identifier
        span_id: Current span identifier
        event_type: Event type (e.g., 'model_request', 'tool_end') — see EventType

    Optional fields:
        agent_name: Name of the agent
        tool_name: Name of the tool being called
        model_name: Name of the model being used
        data: Additional event-specific data
        framework: Framework that generated this event
    """
    # Required fields
    event_id: str
    timestamp: float
    trace_id: str
    session_id: str
    span_id: str
    event_type: str

    # Optional fields
    agent_name: Optional[str] = None
    tool_name: Optional[str] = None
    model_name: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    framework: FrameworkName = "unknown"
    skill_name: Optional[str] = None  # MCP skill identifier (analogous to tool_name for MCP proxy events)

    # Host context — populated automatically by create_event() from the cached
    # HostContext. Sources MAY pre-set any of these (e.g. a remote relay
    # forwarding events from another machine) and create_event won't clobber.
    host: Optional[str] = None
    user: Optional[str] = None
    os: Optional[str] = None
    arch: Optional[str] = None
    library_version: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate event fields after initialization."""
        if not self.event_id:
            raise ValueError("event_id cannot be empty")
        if not self.trace_id:
            raise ValueError("trace_id cannot be empty")
        if not self.session_id:
            raise ValueError("session_id cannot be empty")
        if not self.span_id:
            raise ValueError("span_id cannot be empty")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if not self.event_type:
            raise ValueError("event_type cannot be empty")


def create_event(
    event_type: str,
    agent_name: Optional[str] = None,
    tool_name: Optional[str] = None,
    model_name: Optional[str] = None,
    framework: FrameworkName = "unknown",
    skill_name: Optional[str] = None,
    **kwargs: Any
) -> TelemetryEvent:
    """Create a new telemetry event with context propagation.

    Automatically populates trace_id, session_id, span_id from context,
    and generates event_id and timestamp.

    Args:
        event_type: Type of event (e.g., 'model_request', 'tool_end') — see EventType
        agent_name: Optional name of the agent
        tool_name: Optional name of the tool
        model_name: Optional name of the model
        framework: Framework that generated this event (default: 'unknown')
        **kwargs: Additional data to store in the event's data field

    Returns:
        Frozen TelemetryEvent instance
    """
    # Merge canonical schema defaults with provided kwargs.
    # Schema provides None defaults for all canonical fields; kwargs override with real values.
    # This ensures every event type always has the same keys in data, regardless of framework.
    schema_defaults = _EVENT_SCHEMAS.get(event_type, {})
    merged = {**schema_defaults, **kwargs}

    # CIM contract: every event carries data.action + data.vendor; terminal
    # events also carry data.result. Adapters MAY override any of these by
    # passing the key explicitly; we only fill when absent.
    if "action" not in merged:
        merged["action"] = _cim.action_for_event_type(event_type)
    if "vendor" not in merged:
        merged["vendor"] = _cim.vendor_from_model_or_framework(model_name, framework)
    if "result" not in merged:
        default_result = _cim.default_result_for_event_type(event_type)
        if default_result is not None:
            merged["result"] = default_result
    # For tool calls, auto-derive reversibility from the tool name when the
    # adapter didn't pre-set it. Mirrors what the Rust hook parser does.
    if (
        event_type in ("tool_start", "tool_end", "tool_error")
        and "reversible" not in merged
    ):
        rev = _cim.classify_reversibility(tool_name)
        if rev is not None:
            merged["reversible"] = rev

    if "log_source_type" not in merged:
        merged["log_source_type"] = _cim.PRODUCT_ID

    # Evaluate detection rules against the unredacted merged dict so boolean/numeric
    # fields (has_injection_patterns, error_class, total_tokens, etc.) retain real values.
    rule_annotations = evaluate_rules(event_type, merged)

    # Apply hot/cold path redaction to merged data before event construction
    if merged:
        if is_hot_path(event_type):
            # Hot path: replace string values with None (keeps keys for uniform schema),
            # pass numeric/bool/None values through unchanged.
            # Exception: CIM-vocabulary keys (vendor, action, result, ...) carry enum
            # values that are classification metadata, never PII — preserve them so
            # downstream SIEM parsers keep their CIM alignment.
            data = {
                k: (
                    v
                    if (not isinstance(v, str) or k in HOT_PATH_SAFE_STRING_KEYS)
                    else None
                )
                for k, v in merged.items()
            }
            # If all values are None and dict would be meaningless, keep it (uniform schema)
            data = data if data else None
        else:
            # Cold path (or unclassified): apply full recursive redaction
            data = _redactor.redact_dict(merged)
    else:
        data = None

    # Merge rule annotations post-redaction so they are never stripped or redacted.
    # triggered_rules and max_severity are safe metadata, not PII.
    if rule_annotations:
        data = {**(data or {}), **rule_annotations}

    ctx = get_host_context()
    event = TelemetryEvent(
        event_id=generate_ulid(),
        timestamp=generate_timestamp(),
        trace_id=get_trace_id(),
        session_id=get_session_id(),
        span_id=get_span_id(),
        event_type=event_type,
        agent_name=agent_name,
        tool_name=tool_name,
        model_name=model_name,
        data=data,
        framework=framework,
        host=ctx.host,
        user=ctx.user,
        os=ctx.os,
        arch=ctx.arch,
        library_version=ctx.library_version,
        skill_name=skill_name,
    )
    logger.debug("Created event: type=%s, event_id=%s", event_type, event.event_id)
    return event
