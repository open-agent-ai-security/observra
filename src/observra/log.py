# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Explicit logging API for framework-agnostic agent telemetry.

Provides 12 event functions (+ ``set_framework()``) that developers call
directly so every agent on every framework produces the same canonical events.
Coexists with passive adapters — deduplication via ``core.dedup`` prevents
double-counting when both fire.

All functions are safe to call without ``initialize()`` — they degrade
gracefully (log a warning, never raise).

Usage::

    import observra
    from observra import log

    observra.initialize(backend="jsonl", path="telemetry.jsonl")
    log.set_framework("openai")

    log.session_start(agent_name="my-agent")
    log.model_request(model_name="gpt-4o")
    log.model_response("gpt-4o", input_tokens=500, output_tokens=200)
    log.session_end(agent_name="my-agent")
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from decimal import Decimal
from typing import Optional

from .core.context import (
    add_to_session_cost,
    get_span_id,
    initialize_trace,
    new_span,
    reset_session_cost,
)
from .core.dedup import register_emission, reset_dedup
from .core.detection import (
    classify_error,
    decrement_delegation_depth,
    increment_delegation_depth,
    initialize_delegation_depth,
)
from .core.events import EventType, create_event
from .core.injection import detect_injection_patterns
from .core.sequences import (
    get_tool_sequence,
    initialize_tool_sequence,
    record_tool_call,
)
from .core.velocity import initialize_velocity_tracker, record_token_usage

logger = logging.getLogger(__name__)

# ── Module state ──────────────────────────────────────────────────────────────

_framework: str = "unknown"

# Cost threshold once-per-session flag (ContextVar for concurrent safety).
_threshold_emitted_var: ContextVar[bool] = ContextVar("log_threshold_emitted", default=False)


# ── Late-binding helpers (read module state at call time) ─────────────────────


def _get_queue():
    """Return the module-level ``_queue_proxy`` from ``observra``."""
    import observra as _at

    return _at._queue_proxy


def _get_cost_calculator():
    """Return the module-level ``_cost_calculator`` from ``observra``."""
    import observra as _at

    return _at._cost_calculator


def _get_cost_threshold():
    """Return the module-level ``_cost_threshold`` from ``observra``."""
    import observra as _at

    return _at._cost_threshold


def _get_max_sequence_length() -> int:
    """Return the module-level ``_max_sequence_length`` from ``observra``."""
    import observra as _at

    return _at._max_sequence_length


# ── Internal helpers ──────────────────────────────────────────────────────────


def _emit(event) -> None:
    """Push *event* to the queue proxy.  Never raises."""
    try:
        q = _get_queue()
        q.put_nowait(event)
    except Exception as exc:
        logger.warning(f"log._emit failed for {event.event_type}: {exc}")


def _model_response_metrics(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    framework: str,
) -> dict:
    """Calculate the metrics shared by model-response emitters."""
    total_tokens = input_tokens + output_tokens
    cost = session_total = tokens_per_minute = Decimal("0")
    calculator = _get_cost_calculator()
    if calculator is not None:
        cost = calculator.calculate_cost(model_name, input_tokens, output_tokens, cached_tokens)
        session_total = add_to_session_cost(cost)
        tokens_per_minute = record_token_usage(total_tokens)

        threshold = _get_cost_threshold()
        if threshold is not None and not _threshold_emitted_var.get() and session_total >= threshold:
            _threshold_emitted_var.set(True)
            _emit(
                create_event(
                    event_type=EventType.COST_THRESHOLD_EXCEEDED,
                    framework=framework,
                    session_cost_usd=float(session_total),
                    threshold_usd=float(threshold),
                    message=f"Session cost ${session_total:.6f} exceeded threshold ${threshold:.2f}",
                )
            )

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens or None,
        "total_tokens": total_tokens,
        "cost_usd": float(cost),
        "session_cost_usd": float(session_total),
        "tokens_per_minute": float(tokens_per_minute),
    }


def _get_sequence_payload(raw_sequence: list) -> dict:
    """Build tool_sequence payload with truncation — mirrors TelemetryPlugin."""
    max_len = _get_max_sequence_length()
    total_length = len(raw_sequence)
    if total_length > max_len:
        raw_sequence = raw_sequence[-max_len:]
    tool_sequence = [{"tool": t, "ts": ts} for t, ts in raw_sequence]
    return {
        "tool_sequence": tool_sequence,
        "sequence_length": total_length,
        "sequence_total_length": total_length,
    }


# ── Public API ────────────────────────────────────────────────────────────────


def set_framework(name: str) -> None:
    """Set the framework name used for all subsequent ``log.*()`` calls.

    Args:
        name: Framework identifier (e.g. ``"openai"``, ``"adk"``, ``"claude"``).
    """
    global _framework
    _framework = name


def session_start(*, agent_name: Optional[str] = None) -> None:
    """Emit ``session_start`` and initialise trace context."""
    try:
        initialize_trace()
        reset_dedup()
        reset_session_cost()
        _threshold_emitted_var.set(False)
        initialize_velocity_tracker()
        initialize_tool_sequence()
        initialize_delegation_depth()

        span_id = get_span_id()
        if not register_emission(EventType.SESSION_START, span_id, source="log"):
            return

        event = create_event(
            event_type=EventType.SESSION_START,
            agent_name=agent_name,
            framework=_framework,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.session_start failed: {exc}")


def session_end(*, agent_name: Optional[str] = None) -> None:
    """Emit ``session_end`` with tool-sequence summary."""
    try:
        span_id = get_span_id()
        if not register_emission(EventType.SESSION_END, span_id, source="log"):
            return

        raw_sequence = get_tool_sequence()
        seq_payload = _get_sequence_payload(raw_sequence)

        event = create_event(
            event_type=EventType.SESSION_END,
            agent_name=agent_name,
            framework=_framework,
            **seq_payload,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.session_end failed: {exc}")


def agent_start(agent_name: str) -> None:
    """Emit ``agent_start``, track delegation depth."""
    try:
        new_span()
        current_depth, depth_exceeded = increment_delegation_depth()

        if depth_exceeded:
            from .core.detection import MAX_DELEGATION_DEPTH

            depth_event = create_event(
                event_type=EventType.DEPTH_EXCEEDED,
                agent_name=agent_name,
                framework=_framework,
                current_depth=current_depth,
                max_depth=MAX_DELEGATION_DEPTH,
                message=f"Agent {agent_name} exceeded max delegation depth ({current_depth} > {MAX_DELEGATION_DEPTH})",
            )
            _emit(depth_event)

        span_id = get_span_id()
        if not register_emission(EventType.AGENT_START, span_id, source="log"):
            return

        event = create_event(
            event_type=EventType.AGENT_START,
            agent_name=agent_name,
            framework=_framework,
            delegation_depth=current_depth,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.agent_start failed: {exc}")


def agent_end(agent_name: str) -> None:
    """Emit ``agent_end``, decrement delegation depth."""
    try:
        current_depth = decrement_delegation_depth()

        span_id = get_span_id()
        if not register_emission(EventType.AGENT_END, span_id, source="log"):
            return

        event = create_event(
            event_type=EventType.AGENT_END,
            agent_name=agent_name,
            framework=_framework,
            delegation_depth=current_depth,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.agent_end failed: {exc}")


def model_request(model_name: str) -> None:
    """Emit ``model_request``."""
    try:
        span_id = get_span_id()
        if not register_emission(EventType.MODEL_REQUEST, span_id, source="log"):
            return

        event = create_event(
            event_type=EventType.MODEL_REQUEST,
            model_name=model_name,
            framework=_framework,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.model_request failed: {exc}")


def model_response(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> None:
    """Emit ``model_response`` with cost calculation and velocity tracking."""
    try:
        span_id = get_span_id()
        if not register_emission(EventType.MODEL_RESPONSE, span_id, source="log"):
            return

        metrics = _model_response_metrics(model_name, input_tokens, output_tokens, cached_tokens, _framework)
        event = create_event(
            event_type=EventType.MODEL_RESPONSE,
            model_name=model_name,
            framework=_framework,
            reasoning_tokens=reasoning_tokens or None,
            **metrics,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.model_response failed: {exc}")


def model_error(
    *,
    model_name: Optional[str] = None,
    error: Optional[Exception] = None,
) -> None:
    """Emit ``model_error`` with error classification."""
    try:
        span_id = get_span_id()
        if not register_emission(EventType.MODEL_ERROR, span_id, source="log"):
            return

        error_class = "unknown"
        is_retryable = False
        error_type_name = None
        error_message = None

        if error is not None:
            error_class, is_retryable = classify_error(error, context="model")
            error_type_name = type(error).__name__
            error_message = str(error)

        event = create_event(
            event_type=EventType.MODEL_ERROR,
            model_name=model_name,
            framework=_framework,
            error_class=error_class,
            is_retryable=is_retryable,
            error_type_name=error_type_name,
            error_message=error_message,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.model_error failed: {exc}")


def tool_start(tool_name: str, *, tool_args: Optional[str] = None) -> None:
    """Emit ``tool_start``, record tool call in sequence tracker."""
    try:
        new_span()
        raw_sequence = record_tool_call(tool_name)
        seq_payload = _get_sequence_payload(raw_sequence)

        span_id = get_span_id()
        if not register_emission(EventType.TOOL_START, span_id, source="log"):
            return

        event_kwargs = dict(
            event_type=EventType.TOOL_START,
            tool_name=tool_name,
            framework=_framework,
            **seq_payload,
        )
        if tool_args is not None:
            event_kwargs["tool_args"] = tool_args

        event = create_event(**event_kwargs)
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.tool_start failed: {exc}")


def tool_end(
    tool_name: str,
    *,
    duration_ms: Optional[float] = None,
    tool_result: Optional[str] = None,
) -> None:
    """Emit ``tool_end`` with optional duration and result."""
    try:
        raw_sequence = get_tool_sequence()
        seq_payload = _get_sequence_payload(raw_sequence)

        span_id = get_span_id()
        if not register_emission(EventType.TOOL_END, span_id, source="log"):
            return

        event_kwargs = dict(
            event_type=EventType.TOOL_END,
            tool_name=tool_name,
            framework=_framework,
            **seq_payload,
        )
        if duration_ms is not None:
            event_kwargs["duration_ms"] = duration_ms
        if tool_result is not None:
            event_kwargs["tool_result"] = tool_result

        event = create_event(**event_kwargs)
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.tool_end failed: {exc}")


def tool_error(tool_name: str, *, error: Optional[Exception] = None) -> None:
    """Emit ``tool_error`` with error classification."""
    try:
        span_id = get_span_id()
        if not register_emission(EventType.TOOL_ERROR, span_id, source="log"):
            return

        error_class = "unknown"
        is_retryable = False
        error_type_name = None
        error_message = None

        if error is not None:
            error_class, is_retryable = classify_error(error, context="tool")
            error_type_name = type(error).__name__
            error_message = str(error)

        event = create_event(
            event_type=EventType.TOOL_ERROR,
            tool_name=tool_name,
            framework=_framework,
            error_class=error_class,
            is_retryable=is_retryable,
            error_type_name=error_type_name,
            error_message=error_message,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.tool_error failed: {exc}")


def user_message(text: str, *, user_id: Optional[str] = None) -> None:
    """Emit ``user_message`` with injection pattern detection."""
    try:
        span_id = get_span_id()
        if not register_emission(EventType.USER_MESSAGE, span_id, source="log"):
            return

        injection_patterns = detect_injection_patterns(text)

        event = create_event(
            event_type=EventType.USER_MESSAGE,
            framework=_framework,
            user_id=user_id,
            user_message_text=text,
            has_injection_patterns=len(injection_patterns) > 0,
            injection_patterns=injection_patterns if injection_patterns else None,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.user_message failed: {exc}")


def agent_handoff(source_agent: str, target_agent: str) -> None:
    """Emit ``agent_handoff``."""
    try:
        span_id = get_span_id()
        if not register_emission(EventType.AGENT_HANDOFF, span_id, source="log"):
            return

        event = create_event(
            event_type=EventType.AGENT_HANDOFF,
            framework=_framework,
            source_agent=source_agent,
            target_agent=target_agent,
        )
        _emit(event)
    except Exception as exc:
        logger.warning(f"log.agent_handoff failed: {exc}")


def emit(
    event_type: str,
    *,
    agent_name: Optional[str] = None,
    tool_name: Optional[str] = None,
    model_name: Optional[str] = None,
    framework: Optional[str] = None,
    **data,
) -> None:
    """Emit an event from a host without a shipped adapter."""
    try:
        framework = framework or _framework
        if not register_emission(event_type, get_span_id(), source="log"):
            return

        text = data.get("user_message_text")
        if isinstance(text, str) and text:
            patterns = detect_injection_patterns(text)
            data["has_injection_patterns"] = bool(patterns)
            data["injection_patterns"] = patterns or None

        if (
            event_type == EventType.MODEL_RESPONSE
            and data.get("cost_usd") is None
            and isinstance(data.get("input_tokens"), int)
            and isinstance(data.get("output_tokens"), int)
        ):
            data.update(
                _model_response_metrics(
                    model_name or "unknown",
                    data["input_tokens"],
                    data["output_tokens"],
                    data.get("cached_tokens") or 0,
                    framework,
                )
            )

        _emit(
            create_event(
                event_type=event_type,
                agent_name=agent_name,
                tool_name=tool_name,
                model_name=model_name,
                framework=framework,
                **data,
            )
        )
    except Exception as exc:
        logger.warning(f"log.emit failed: {exc}")
