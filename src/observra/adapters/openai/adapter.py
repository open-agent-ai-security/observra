"""OpenAIAdapter: OpenAI Agents SDK adapter for agent telemetry.

Implements TracingProcessor from the OpenAI Agents SDK and satisfies the
FrameworkAdapter Protocol. Intercepts all span lifecycle events and maps them
to TelemetryEvents:

    AgentSpanData   -> session_start (on_span_start) + session_end (on_span_end)
    GenerationSpanData -> model_response (on_span_end) with exact token data and cost
    FunctionSpanData -> tool_call (on_span_end) with duration_ms
    HandoffSpanData  -> handoff (on_span_end) with source/target agent and trigger context

All 6 TracingProcessor methods are synchronous — no asyncio.run() or await anywhere.
Token data comes directly from GenerationSpanData.usage (no estimation needed).
reasoning_tokens is tracked separately but NOT double-billed with output_tokens.

Observation-only guarantee: every callback catches all exceptions internally so the
OpenAI Agents SDK run is never disrupted by telemetry errors.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from agents.tracing import TracingProcessor
from agents.tracing.span_data import (
    AgentSpanData,
    FunctionSpanData,
    GenerationSpanData,
    HandoffSpanData,
)

from observra.adapters.utils import normalize_openai_tokens, safe_serialize
from observra.core.context import initialize_session, initialize_trace
from observra.core.cost import CostCalculator
from observra.core.dedup import register_emission, reset_dedup
from observra.core.events import TelemetryEvent, create_event

logger = logging.getLogger(__name__)


class OpenAIAdapter(TracingProcessor):
    """OpenAI Agents SDK adapter that captures all span lifecycle events.

    Subclasses TracingProcessor from the OpenAI Agents SDK and satisfies the
    FrameworkAdapter Protocol:
        - framework_name property returns "openai"
        - emit() routes events to queue or in-memory list
        - get_adapter_stats() returns error/drop counters

    All 6 TracingProcessor callbacks are synchronous (no asyncio.run() or await).
    Token data is exact from GenerationSpanData.usage — not estimated.
    reasoning_tokens tracked separately, not double-billed with output_tokens.

    Usage::

        adapter = OpenAIAdapter(capture_tool_data=True)
        from agents import set_tracing_processor
        set_tracing_processor(adapter)
        result = await Runner.run(agent, prompt)
    """

    def __init__(
        self,
        queue=None,
        cost_calculator: Optional[CostCalculator] = None,
        cost_threshold_usd=None,
        capture_tool_data: bool = False,
        payload_max_bytes: int = 4096,
    ) -> None:
        """Initialize OpenAIAdapter.

        Args:
            queue: Optional DropOldestQueue for async event processing.
                   If None, events are stored in-memory (Phase 1 behavior).
            cost_calculator: Optional CostCalculator with OpenAI pricing.
                             If None, creates one from co-located pricing.json.
            cost_threshold_usd: Optional cost threshold in USD. When a generation
                                 span's cost >= threshold, emits cost_threshold_exceeded
                                 event (once per adapter lifetime).
            capture_tool_data: If True, serialize tool args and results into events.
                                Default False for privacy.
            payload_max_bytes: Max bytes for tool data serialization (default 4096).
        """
        self._queue = queue
        self._events: list[TelemetryEvent] = []
        self._enabled: bool = True
        self._cost_threshold = cost_threshold_usd
        self._capture_tool_data = capture_tool_data
        self._payload_max_bytes = payload_max_bytes
        self._error_count: int = 0
        self._dropped_events: int = 0
        self._events_captured: int = 0

        # Cost threshold deduplication: emit once per adapter lifetime
        self._cost_threshold_emitted: bool = False

        # Function span metadata: span_id -> {"name": ..., "input": ...}
        # Used for handoff trigger context (which tool triggered the handoff)
        self._function_spans: dict[str, dict] = {}

        # Initialize cost calculator with OpenAI-specific pricing
        if cost_calculator is not None:
            self._cost_calculator = cost_calculator
        else:
            pricing_path = Path(__file__).parent / "pricing.json"
            self._cost_calculator = CostCalculator(str(pricing_path))

        logger.debug(
            f"OpenAIAdapter initialized (queue={'async' if queue else 'in-memory'}, "
            f"threshold={'$' + str(cost_threshold_usd) if cost_threshold_usd else 'none'}, "
            f"capture_tool_data={capture_tool_data})"
        )

    # ========================================================================
    # FrameworkAdapter Protocol
    # ========================================================================

    @property
    def framework_name(self) -> str:
        """Return the framework identifier for this adapter."""
        return "openai"

    def emit(self, event: TelemetryEvent) -> None:
        """Route event to queue or in-memory list (FrameworkAdapter Protocol).

        Observation-only guarantee: never raises. On any exception, increments
        _error_count and logs the error so callers are never disrupted.

        Includes dedup check: if the explicit ``log.*()`` API already emitted
        the same (event_type, span_id) pair, this emission is skipped.

        Args:
            event: TelemetryEvent to store
        """
        if not self._enabled:
            self._dropped_events += 1
            return
        try:
            if not register_emission(event.event_type, event.span_id):
                logger.debug(f"Dedup skip in adapter emit: {event.event_type}")
                return
            if self._queue is not None:
                self._queue.put_nowait(event)
                logger.debug(f"Event enqueued: {event.event_type}")
            else:
                self._events.append(event)
                self._events_captured += 1
                logger.debug(f"Event captured: {event.event_type}")
        except Exception as e:
            self._error_count += 1
            logger.error(f"emit() error for event {event.event_type}: {e}", exc_info=True)

    def get_adapter_stats(self) -> dict:
        """Return adapter-level error and drop counters for monitoring.

        Returns:
            Dictionary with framework, error_count, dropped_events, events_captured.
        """
        return {
            "framework": self.framework_name,
            "error_count": self._error_count,
            "dropped_events": self._dropped_events,
            "events_captured": self._events_captured,
        }

    @property
    def events(self) -> list[TelemetryEvent]:
        """Return copy of internal event list to prevent external mutation."""
        return self._events.copy()

    # ========================================================================
    # TracingProcessor — 6 synchronous methods (no asyncio.run() or await)
    # ========================================================================

    def on_trace_start(self, trace: Any) -> None:
        """TracingProcessor callback: trace started.

        No-op: Agent span handles session lifecycle via on_span_start.
        """
        pass

    def on_trace_end(self, trace: Any) -> None:
        """TracingProcessor callback: trace ended.

        No-op: Agent span handles session lifecycle via on_span_end.
        """
        pass

    def on_span_start(self, span: Any) -> None:
        """TracingProcessor callback: span started.

        Handles AgentSpanData: initializes trace/session context and emits
        session_start event so context vars are set BEFORE any nested spans fire.

        Args:
            span: OpenAI Agents SDK Span object
        """
        try:
            if isinstance(span.span_data, AgentSpanData):
                # Initialize context before any nested spans fire
                initialize_trace()
                initialize_session()
                reset_dedup()
                data = span.span_data
                event = create_event(
                    event_type="session_start",
                    agent_name=data.name,
                    framework="openai",
                )
                self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.error(f"OpenAIAdapter error in on_span_start: {e}", exc_info=True)

    def on_span_end(self, span: Any) -> None:
        """TracingProcessor callback: span ended.

        Dispatches to type-specific handlers based on span_data type.
        Silently skips unrecognized span types (GuardrailSpanData, etc.).

        Args:
            span: OpenAI Agents SDK Span object
        """
        try:
            data = span.span_data
            if isinstance(data, AgentSpanData):
                self._handle_agent_span(span, data)
            elif isinstance(data, GenerationSpanData):
                self._handle_generation_span(span, data)
            elif isinstance(data, FunctionSpanData):
                self._handle_function_span(span, data)
            elif isinstance(data, HandoffSpanData):
                self._handle_handoff_span(span, data)
            # Other types (GuardrailSpanData, MCPListToolsSpanData): skip silently
        except Exception as e:
            self._error_count += 1
            logger.error(f"OpenAIAdapter error in on_span_end: {e}", exc_info=True)

    def shutdown(self) -> None:
        """TracingProcessor callback: adapter shutdown.

        Logs adapter stats at info level for observability.
        """
        stats = self.get_adapter_stats()
        logger.info(
            f"OpenAIAdapter shutdown: framework={stats['framework']}, "
            f"events_captured={stats['events_captured']}, "
            f"error_count={stats['error_count']}, "
            f"dropped_events={stats['dropped_events']}"
        )

    def force_flush(self) -> None:
        """TracingProcessor callback: force flush pending events.

        No-op: in-memory append is immediate and queue.put_nowait() is non-blocking.
        """
        pass

    # ========================================================================
    # Span handlers
    # ========================================================================

    def _handle_agent_span(self, span: Any, data: AgentSpanData) -> None:
        """Emit session_end event for a completed agent span.

        Args:
            span: Completed agent span
            data: AgentSpanData with name, tools, handoffs, output_type
        """
        event_kwargs: dict[str, Any] = dict(
            event_type="session_end",
            agent_name=data.name,
            framework="openai",
            tools=data.tools,
            handoffs=data.handoffs,
            output_type=data.output_type,
        )
        if span.error is not None:
            event_kwargs["error_message"] = str(span.error)

        event = create_event(**event_kwargs)
        self.emit(event)

    def _handle_generation_span(self, span: Any, data: GenerationSpanData) -> None:
        """Emit model_response event for a completed generation span.

        Uses exact token data from GenerationSpanData.usage — no estimation needed.
        reasoning_tokens tracked separately, NOT added to output_tokens for cost.

        Args:
            span: Completed generation span
            data: GenerationSpanData with model, usage, output
        """
        tokens = normalize_openai_tokens(data.usage)
        model_name = data.model or "unknown"

        if tokens is not None:
            cost = self._cost_calculator.calculate_cost(
                model_name,
                tokens.input_tokens,
                tokens.output_tokens,
                tokens.cached_tokens or 0,
            )

            event_kwargs: dict[str, Any] = dict(
                event_type="model_response",
                model_name=model_name,
                framework="openai",
                cost_usd=float(cost),
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                total_tokens=tokens.total_tokens,
            )

            if tokens.cached_tokens is not None:
                event_kwargs["cached_tokens"] = tokens.cached_tokens

            if tokens.reasoning_tokens is not None:
                event_kwargs["reasoning_tokens"] = tokens.reasoning_tokens
        else:
            # No usage data: emit event without token/cost fields
            cost = None
            event_kwargs = dict(
                event_type="model_response",
                model_name=model_name,
                framework="openai",
            )

        # Capture tool calls from generation output if enabled
        if data.output and self._capture_tool_data:
            tool_calls = []
            for item in data.output:
                if isinstance(item, dict) and item.get("type") in ("function_call", "tool_call"):
                    tool_calls.append(item)
            if tool_calls:
                event_kwargs["tool_calls_in_generation"] = safe_serialize(tool_calls, self._payload_max_bytes)

        if span.error is not None:
            event_kwargs["error_message"] = str(span.error)

        event = create_event(**event_kwargs)
        self.emit(event)

        # Emit cost_threshold_exceeded if threshold crossed (once per lifetime)
        if (
            cost is not None
            and self._cost_threshold is not None
            and float(cost) >= float(self._cost_threshold)
            and not self._cost_threshold_emitted
        ):
            self._cost_threshold_emitted = True
            threshold_event = create_event(
                event_type="cost_threshold_exceeded",
                framework="openai",
                session_cost_usd=float(cost),
                threshold_usd=float(self._cost_threshold),
                exceeded=True,
            )
            self.emit(threshold_event)

    def _handle_function_span(self, span: Any, data: FunctionSpanData) -> None:
        """Emit tool_call event for a completed function span.

        Also stores function span metadata for handoff trigger context lookup.

        Args:
            span: Completed function span
            data: FunctionSpanData with name, input, output
        """
        duration_ms = self._compute_duration(span)

        event_kwargs: dict[str, Any] = dict(
            event_type="tool_end",
            tool_name=data.name,
            framework="openai",
        )

        if duration_ms is not None:
            event_kwargs["duration_ms"] = duration_ms

        if self._capture_tool_data:
            if data.input is not None:
                event_kwargs["tool_args"] = safe_serialize(data.input, self._payload_max_bytes)
            if data.output is not None:
                event_kwargs["tool_result"] = safe_serialize(data.output, self._payload_max_bytes)

        if span.error is not None:
            event_kwargs["error_message"] = str(span.error)
            event_kwargs["error_type_name"] = type(span.error).__name__

        event = create_event(**event_kwargs)
        self.emit(event)

        # Store metadata for handoff trigger context (keyed by span_id)
        self._function_spans[span.span_id] = {
            "name": data.name,
            "input": safe_serialize(data.input, 256) if data.input is not None else None,
        }

    def _handle_handoff_span(self, span: Any, data: HandoffSpanData) -> None:
        """Emit handoff event for a completed handoff span.

        Looks up parent function span for trigger context (which tool initiated handoff).
        Also emits handoff_error for failed handoffs.

        Args:
            span: Completed handoff span
            data: HandoffSpanData with from_agent and to_agent
        """
        event_kwargs: dict[str, Any] = dict(
            event_type="agent_handoff",
            framework="openai",
            source_agent=data.from_agent,
            target_agent=data.to_agent,
        )

        # Capture trigger context from parent function span
        parent_id = getattr(span, "parent_id", None)
        if parent_id and parent_id in self._function_spans:
            trigger = self._function_spans[parent_id]
            event_kwargs["trigger_tool"] = trigger["name"]
            event_kwargs["trigger_args"] = trigger["input"]

        event = create_event(**event_kwargs)
        self.emit(event)

        # Emit separate handoff_error event for failed handoffs
        if span.error is not None:
            error_event = create_event(
                event_type="agent_handoff_error",
                framework="openai",
                source_agent=data.from_agent,
                target_agent=data.to_agent,
                error_message=str(span.error),
            )
            self.emit(error_event)

    # ========================================================================
    # Helpers
    # ========================================================================

    def _compute_duration(self, span: Any) -> Optional[float]:
        """Compute span duration in milliseconds from ISO timestamps.

        Args:
            span: Span object with started_at and ended_at ISO timestamp strings

        Returns:
            Duration in milliseconds, or None if timestamps are unavailable/unparseable
        """
        try:
            started_at = getattr(span, "started_at", None)
            ended_at = getattr(span, "ended_at", None)
            if started_at is None or ended_at is None:
                return None
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            return (end - start).total_seconds() * 1000.0
        except Exception:
            return None
