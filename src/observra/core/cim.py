"""Cross-source CIM-aligned data block contract — GENERATED FROM cim_schema.toml. DO NOT EDIT."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

CIM_VERSION = "1.0"
PRODUCT_ID = "observra"


# ---------------------------------------------------------------------------
# Enumerations — canonical values for SIEM-friendly fields.
# ---------------------------------------------------------------------------

class Action(str, Enum):
    ACCESS_FILE    = "access_file"
    CALL_LLM       = "call_llm"
    EXECUTE_CODE   = "execute_code"
    INVOKE_AGENT   = "invoke_agent"
    READ_MEMORY    = "read_memory"
    SEND_EXTERNAL  = "send_external"
    WRITE_MEMORY   = "write_memory"
    INVOKE_TOOL    = "invoke_tool"
    UNKNOWN        = "unknown"

class Vendor(str, Enum):
    ANTHROPIC      = "anthropic"
    GOOGLE         = "google"
    MICROSOFT      = "microsoft"
    OPENAI         = "openai"
    UNKNOWN        = "unknown"

class ActionResult(str, Enum):
    SUCCESS        = "success"
    FAILURE        = "failure"
    BLOCKED        = "blocked"
    TIMEOUT        = "timeout"

class FinishReason(str, Enum):
    CONTENT_FILTER = "content_filter"
    MAX_TOKENS     = "max_tokens"
    STOP           = "stop"
    TOOL_CALL      = "tool_call"
    ERROR          = "error"
    TIMEOUT        = "timeout"
    UNKNOWN        = "unknown"

_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "tool_calls": FinishReason.TOOL_CALL,
    "function_call": FinishReason.TOOL_CALL,
    "length": FinishReason.MAX_TOKENS,
    "content_filter": FinishReason.CONTENT_FILTER,
    "end_turn": FinishReason.STOP,
    "tool_use": FinishReason.TOOL_CALL,
    "max_tokens": FinishReason.MAX_TOKENS,
    "stop_sequence": FinishReason.STOP,
    "STOP": FinishReason.STOP,
    "MAX_TOKENS": FinishReason.MAX_TOKENS,
    "SAFETY": FinishReason.CONTENT_FILTER,
    "RECITATION": FinishReason.CONTENT_FILTER,
    "FINISH_REASON_STOP": FinishReason.STOP,
    "FINISH_REASON_MAX_TOKENS": FinishReason.MAX_TOKENS,
    "finished": FinishReason.STOP,
    "filtered": FinishReason.CONTENT_FILTER,
}

def normalize_finish_reason(raw: Optional[str]) -> FinishReason:
    """Map platform finish_reason string to canonical FinishReason."""
    if not raw:
        return FinishReason.UNKNOWN
    return _FINISH_REASON_MAP.get(raw, FinishReason.UNKNOWN)


# ---------------------------------------------------------------------------
# Tool name → action vocabulary.
# ---------------------------------------------------------------------------

_ACTION_PATTERNS: list[tuple[str, Action]] = [
    ("bash",          Action.EXECUTE_CODE),
    ("call_llm",      Action.CALL_LLM),
    ("handoff",       Action.INVOKE_AGENT),
    ("http",          Action.SEND_EXTERNAL),
    ("memory_read",   Action.READ_MEMORY),
    ("read_file",     Action.ACCESS_FILE),
    ("memory_write",  Action.WRITE_MEMORY),
    ("model_request", Action.CALL_LLM),
    ("shell",         Action.EXECUTE_CODE),
    ("transfer",      Action.INVOKE_AGENT),
    ("webhook",       Action.SEND_EXTERNAL),
    ("write_file",    Action.ACCESS_FILE),
    ("delegate",      Action.INVOKE_AGENT),
    ("email",         Action.SEND_EXTERNAL),
    ("execute",       Action.EXECUTE_CODE),
    ("file_read",     Action.ACCESS_FILE),
    ("inference",     Action.CALL_LLM),
    ("remember",      Action.WRITE_MEMORY),
    ("file_write",    Action.ACCESS_FILE),
    ("recall",        Action.READ_MEMORY),
    ("run_code",      Action.EXECUTE_CODE),
    ("send_email",    Action.SEND_EXTERNAL),
    ("api_call",      Action.SEND_EXTERNAL),
    ("computer",      Action.EXECUTE_CODE),
    ("file_editor",   Action.ACCESS_FILE),
    ("web_fetch",     Action.SEND_EXTERNAL),
    ("browse",        Action.SEND_EXTERNAL),
    ("search",        Action.SEND_EXTERNAL),
]

def normalize_action(tool_name: Optional[str]) -> Action:
    """Infer the canonical CIM action enum from a free-form tool name."""
    if not tool_name:
        return Action.UNKNOWN
    lower = tool_name.lower()
    for pattern, action in _ACTION_PATTERNS:
        if pattern in lower:
            return action
    return Action.INVOKE_TOOL


# ---------------------------------------------------------------------------
# event_type → CIM action mapping.
# ---------------------------------------------------------------------------

_ACTION_FOR_EVENT_TYPE: dict[str, str] = {
    "adapter_close": "end_session",
    "agent_end": "invoke_agent",
    "agent_handoff": "invoke_agent",
    "agent_handoff_error": "invoke_agent",
    "agent_start": "invoke_agent",
    "compact_boundary": "compact_context",
    "cost_threshold_exceeded": "policy_event",
    "depth_exceeded": "policy_event",
    "forwarder_update_available": "update_available",
    "forwarder_update_failed": "update_failed",
    "forwarder_updated": "update_applied",
    "mcp_session_end": "end_session",
    "mcp_session_start": "start_session",
    "model_error": "call_llm",
    "model_request": "call_llm",
    "model_response": "call_llm",
    "session_end": "end_session",
    "session_start": "start_session",
    "skill_invocation": "tool_call",
    "stream_event": "call_llm",
    "tool_end": "tool_call",
    "tool_error": "tool_call",
    "tool_start": "tool_call",
    "turn": "call_llm",
    "turn_duration": "call_llm",
    "user": "prompt_submit",
    "user_message": "prompt_submit",
}

def action_for_event_type(event_type: str) -> str:
    """Map a canonical event_type to its CIM action verb."""
    return _ACTION_FOR_EVENT_TYPE.get(event_type, "unknown")


# ---------------------------------------------------------------------------
# Default result for terminal events. None for non-terminal events.
# ---------------------------------------------------------------------------

_DEFAULT_RESULT_FOR_EVENT_TYPE: dict[str, str] = {
    "agent_end": "success",
    "agent_handoff_error": "failure",
    "model_error": "failure",
    "model_response": "success",
    "tool_end": "success",
    "tool_error": "failure",
    "turn": "success",
}

def default_result_for_event_type(event_type: str) -> Optional[str]:
    """Return the default data.result for terminal event types."""
    return _DEFAULT_RESULT_FOR_EVENT_TYPE.get(event_type)


# ---------------------------------------------------------------------------
# Vendor derivation from model name.
# ---------------------------------------------------------------------------

def vendor_from_model(model: Optional[str]) -> str:
    """Classify a model identifier into a vendor."""
    if not model:
        return "unknown"
    lower = model.lower()
    if "claude" in lower or "anthropic" in lower:
        return "anthropic"
    if "gpt" in lower or "o1" in lower or "o3" in lower or "openai" in lower:
        return "openai"
    if "gemini" in lower or "google" in lower or "vertex" in lower:
        return "google"
    if "copilot" in lower:
        return "microsoft"
    return "unknown"

_VENDOR_BY_FRAMEWORK: dict[str, str] = {
    "claude": "anthropic",
    "claude_code": "anthropic",
    "openai": "openai",
    "codex_cli": "openai",
    "codex_app": "openai",
    "gemini_cli": "google",
    "copilot": "microsoft",
}

def vendor_from_model_or_framework(
    model: Optional[str], framework: Optional[str]
) -> str:
    """Vendor classification with a framework-name fallback."""
    v = vendor_from_model(model)
    if v != "unknown":
        return v
    if framework:
        return _VENDOR_BY_FRAMEWORK.get(framework, "unknown")
    return "unknown"


# ---------------------------------------------------------------------------
# Tool reversibility classification.
# ---------------------------------------------------------------------------

_IRREVERSIBLE_TOOL_PATTERNS: list[str] = [
    "delete",
    "drop",
    "truncate",
    "remove",
    "destroy",
    "send_email",
    "send_message",
    "publish",
    "post",
    "transfer",
    "pay",
    "charge",
    "deploy",
    "overwrite",
    "format",
    "wipe",
]

_REVERSIBLE_TOOL_PATTERNS: list[str] = [
    "read",
    "get",
    "fetch",
    "list",
    "search",
    "query",
    "draft",
    "preview",
    "analyze",
    "summarize",
]

def classify_reversibility(tool_name: Optional[str]) -> Optional[bool]:
    """Classify a tool name as reversible / irreversible / unknown."""
    if not tool_name:
        return None
    lower = tool_name.lower()
    for pattern in _IRREVERSIBLE_TOOL_PATTERNS:
        if pattern in lower:
            return False
    for pattern in _REVERSIBLE_TOOL_PATTERNS:
        if pattern in lower:
            return True
    return None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_data_for_event(
    event_type: str,
    vendor: str,
    extras: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the canonical data block for event_type."""
    out: dict[str, Any] = {
        "action": action_for_event_type(event_type),
        "vendor": vendor,
    }
    result = default_result_for_event_type(event_type)
    if result is not None:
        out["result"] = result
    if extras:
        out.update(extras)
    return out
