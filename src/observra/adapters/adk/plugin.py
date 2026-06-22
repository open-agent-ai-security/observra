"""TelemetryPlugin: BasePlugin implementation with all 13 lifecycle callbacks.

This module provides the core plugin class that captures every ADK lifecycle event
as a TelemetryEvent, using defensive error handling to ensure observation-only mode.
"""

import logging
import time
from contextvars import ContextVar
from decimal import Decimal

from google.adk.plugins import BasePlugin

from observra.adapters.utils import normalize_adk_tokens
from observra.adapters.utils import safe_serialize as _safe_serialize
from observra.core.context import (
    add_to_session_cost,
    initialize_trace,
    new_span,
    reset_session_cost,
)
from observra.core.cost import CostCalculator
from observra.core.dedup import register_emission, reset_dedup
from observra.core.detection import (
    MAX_DELEGATION_DEPTH,
    classify_error,
    decrement_delegation_depth,
    increment_delegation_depth,
    initialize_delegation_depth,
)
from observra.core.events import TelemetryEvent, create_event
from observra.core.injection import detect_injection_patterns
from observra.core.sequences import get_tool_sequence, initialize_tool_sequence, record_tool_call
from observra.core.velocity import initialize_velocity_tracker, record_token_usage

logger = logging.getLogger(__name__)

# Per-request state via ContextVars (safe for concurrent requests sharing one plugin instance)
_last_model_name_var: ContextVar[str | None] = ContextVar("last_model_name", default=None)
_threshold_exceeded_var: ContextVar[bool] = ContextVar("threshold_exceeded", default=False)
_turn_start_var: ContextVar[float | None] = ContextVar("turn_start", default=None)

# Lazy-loaded MCP tool class for isinstance checks
_McpTool = None


def _get_tool_type(tool) -> str:
    """Determine tool type: 'mcp' for MCP server tools, 'function' for local tools.

    Uses lazy import of McpTool to avoid hard dependency on MCP packages.
    Falls back to 'function' if the import fails or check errors.
    """
    global _McpTool
    if _McpTool is None:
        try:
            from google.adk.tools.mcp_tool import McpTool

            _McpTool = McpTool
        except ImportError:
            _McpTool = type(None)  # Sentinel: never matches isinstance
    try:
        return "mcp" if isinstance(tool, _McpTool) else "function"
    except Exception:
        return "function"


class TelemetryPlugin(BasePlugin):
    """Telemetry plugin that captures all ADK lifecycle events.

    Implements all 13 BasePlugin callbacks in observation mode (returns None).
    Every callback is wrapped in try-except to prevent plugin errors from
    crashing the host agent.

    Phase 1: Events stored in internal in-memory list.
    Phase 2: Events routed to async queue when available, fallback to in-memory.
    """

    def __init__(
        self,
        queue=None,
        cost_calculator: CostCalculator | None = None,
        cost_threshold_usd: Decimal | None = None,
        max_delegation_depth: int | None = None,
        capture_tool_data: bool = False,
        max_sequence_length: int = 100,
    ):
        """Initialize telemetry plugin with optional async queue and cost tracking.

        Args:
            queue: Optional DropOldestQueue for async event processing.
                  If None, falls back to in-memory list (Phase 1 behavior).
            cost_calculator: Optional CostCalculator for token cost computation.
                           If None, creates default calculator with bundled pricing.
            cost_threshold_usd: Optional cost threshold in USD. When exceeded, emits
                              cost_threshold_exceeded event (once per session).
            max_delegation_depth: Optional maximum delegation depth. If not provided,
                                uses module-level constant from detection.py.
            capture_tool_data: If True, capture tool arguments and results in events.
                             Data goes through cold path redaction. Default False.
            max_sequence_length: Maximum number of tool call entries to include in the
                               tool_sequence field of events. When a session exceeds this
                               limit, the most recent N entries are kept (tail truncation).
                               sequence_total_length always reflects the true session depth.
                               Default 100.
        """
        super().__init__(name="telemetry_plugin")
        self._queue = queue
        self._events: list[TelemetryEvent] = []
        self._enabled: bool = True
        self._cost_calculator = cost_calculator or CostCalculator()
        self._cost_threshold = cost_threshold_usd
        self._max_delegation_depth = max_delegation_depth
        self._capture_tool_data = capture_tool_data
        self._max_sequence_length = max_sequence_length
        # Error / drop tracking for FrameworkAdapter Protocol conformance
        self._error_count: int = 0
        self._dropped_events: int = 0
        # NOTE: _last_model_name and _threshold_exceeded moved to module-level
        # ContextVars for concurrent request safety (plugin singleton is shared
        # across all requests in a Runner).
        logger.debug(
            f"TelemetryPlugin initialized (queue={'async' if queue else 'in-memory'}, "
            f"threshold={'$' + str(cost_threshold_usd) if cost_threshold_usd else 'none'}, "
            f"capture_tool_data={capture_tool_data}, max_sequence_length={max_sequence_length})"
        )

    # ========================================================================
    # FrameworkAdapter Protocol
    # ========================================================================

    @property
    def framework_name(self) -> str:
        """Return the framework identifier for this adapter."""
        return "adk"

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
                # Async path: non-blocking queue
                self._queue.put_nowait(event)
                logger.debug(f"Event enqueued: {event.event_type} (trace={event.trace_id[:8]}...)")
            else:
                # Fallback path: in-memory list (Phase 1 behavior)
                self._events.append(event)
                logger.debug(f"Event captured: {event.event_type} (trace={event.trace_id[:8]}...)")
        except Exception as e:
            self._error_count += 1
            logger.error(f"emit() error for event {event.event_type}: {e}", exc_info=True)

    def _emit_event(self, event: TelemetryEvent) -> None:
        """Delegate to emit() — preserves all 13 callback call sites unchanged."""
        self.emit(event)

    def get_adapter_stats(self) -> dict:
        """Return adapter-level error and drop counters for monitoring.

        Returns:
            Dictionary with error_count, dropped_events, and framework name.
        """
        return {
            "error_count": self._error_count,
            "dropped_events": self._dropped_events,
            "framework": self.framework_name,
        }

    @property
    def events(self) -> list[TelemetryEvent]:
        """Return copy of internal event list to prevent external mutation."""
        return self._events.copy()

    def _get_sequence_payload(self, raw_sequence: list) -> dict:
        """Build tool_sequence payload with truncation and metadata.

        Args:
            raw_sequence: list of (tool_name, timestamp) tuples from sequences.py

        Returns:
            dict with tool_sequence (list[dict]), sequence_length (int),
            sequence_total_length (int). Always emits sequence_total_length
            for query consistency — analysts never need to check for its presence.
        """
        total_length = len(raw_sequence)
        # Tail-truncation: keep most recent N entries (not head — context leading to current call matters)
        if total_length > self._max_sequence_length:
            raw_sequence = raw_sequence[-self._max_sequence_length :]
        tool_sequence = [{"tool": t, "ts": ts} for t, ts in raw_sequence]
        return {
            "tool_sequence": tool_sequence,
            "sequence_length": total_length,  # unchanged: cheap filter field, reflects TRUE session length
            "sequence_total_length": total_length,  # always emit for query consistency
        }

    # ========================================================================
    # ADK BasePlugin Lifecycle Callbacks (all 13)
    # ========================================================================

    async def on_user_message_callback(self, *, invocation_context, user_message) -> None:
        """Capture user message event with injection pattern detection.

        Args:
            invocation_context: ADK invocation context
            user_message: User message content

        Returns:
            None (observation mode)
        """
        try:
            agent_name = getattr(invocation_context, "agent_name", None)

            # Extract message text for injection detection
            # user_message can be: str, Content (with .parts[].text), or object with .text
            message_text = ""
            if isinstance(user_message, str):
                message_text = user_message
            elif hasattr(user_message, "parts"):
                # google.genai.types.Content — concatenate text from all parts
                message_text = " ".join(getattr(part, "text", "") or "" for part in (user_message.parts or []))
            elif hasattr(user_message, "text"):
                message_text = user_message.text

            # Detect injection patterns
            injection_patterns = []
            if message_text:
                injection_patterns = detect_injection_patterns(message_text)

            # Extract user_id from invocation context
            user_id = getattr(invocation_context, "user_id", None)

            event = create_event(
                event_type="user_message",
                agent_name=agent_name,
                framework="adk",
                user_id=user_id,
                user_message_text=message_text if message_text else None,
                has_injection_patterns=len(injection_patterns) > 0,
                injection_patterns=injection_patterns if injection_patterns else None,
            )
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in on_user_message_callback: {e}", exc_info=True)
        return None

    async def before_run_callback(self, *, invocation_context) -> None:
        """Capture before_run event and initialize trace context.

        SPECIAL: Initializes trace context for this run. All subsequent callbacks
        within this run will share the same trace_id. Also resets session cost and
        threshold alert flag for new run. Initializes detection signal trackers.

        Args:
            invocation_context: ADK invocation context

        Returns:
            None (observation mode)
        """
        try:
            # Initialize trace context FIRST
            initialize_trace()
            reset_dedup()

            # Reset session cost accumulator for new run
            reset_session_cost()

            # Reset per-request ContextVars for new run
            _threshold_exceeded_var.set(False)
            _last_model_name_var.set(None)
            _turn_start_var.set(None)

            # Initialize detection signal trackers
            initialize_velocity_tracker()
            initialize_tool_sequence()
            initialize_delegation_depth()

            agent_name = getattr(invocation_context, "agent_name", None)
            event = create_event(
                event_type="session_start",
                agent_name=agent_name,
                framework="adk",
            )
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in before_run_callback: {e}", exc_info=True)
        return None

    async def after_run_callback(self, *, invocation_context) -> None:
        """Capture after_run event.

        Also resets delegation depth as a safety net. If a consumer breaks
        the async generator early (e.g., after is_final_response()), the
        after_agent_callback may be skipped, leaving the depth counter off.
        after_run_callback always fires (it's outside the generator), so
        resetting here ensures clean state.

        Args:
            invocation_context: ADK invocation context

        Returns:
            None (observation mode)
        """
        try:
            # Safety net: reset delegation depth in case after_agent was skipped
            # (happens when consumer breaks the async generator early)
            initialize_delegation_depth()

            # Session-level sequence summary — enables full session reconstruction without joining events.
            # NOTE: If session exceeded max_sequence_length, only the most recent N calls are included.
            # The sequence_total_length field reveals the true session depth even when the list is capped.
            raw_sequence = get_tool_sequence()
            seq_payload = self._get_sequence_payload(raw_sequence)

            agent_name = getattr(invocation_context, "agent_name", None)
            event = create_event(
                event_type="session_end",
                agent_name=agent_name,
                framework="adk",
                **seq_payload,
            )
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in after_run_callback: {e}", exc_info=True)
        return None

    async def before_agent_callback(self, *, agent, callback_context) -> None:
        """Capture before_agent event and create agent span with delegation depth tracking.

        SPECIAL: Creates new span for agent-level operation tracking and tracks
        delegation depth. Emits depth_exceeded event when max depth is crossed.

        Args:
            agent: ADK agent instance
            callback_context: ADK callback context

        Returns:
            None (observation mode)
        """
        try:
            # Create new span for agent-level operation
            new_span()

            agent_name = getattr(agent, "name", None)

            # Track delegation depth
            current_depth, depth_exceeded = increment_delegation_depth()

            # Emit depth_exceeded event if threshold crossed
            if depth_exceeded:
                max_depth = MAX_DELEGATION_DEPTH
                depth_event = create_event(
                    event_type="depth_exceeded",
                    agent_name=agent_name,
                    framework="adk",
                    current_depth=current_depth,
                    max_depth=max_depth,
                    message=f"Agent {agent_name} exceeded max delegation depth ({current_depth} > {max_depth})",
                )
                self._emit_event(depth_event)

            event = create_event(
                event_type="agent_start",
                agent_name=agent_name,
                framework="adk",
                delegation_depth=current_depth,
            )
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in before_agent_callback: {e}", exc_info=True)
        return None

    async def after_agent_callback(self, *, agent, callback_context) -> None:
        """Capture after_agent event with delegation depth decrement.

        Args:
            agent: ADK agent instance
            callback_context: ADK callback context

        Returns:
            None (observation mode)
        """
        try:
            agent_name = getattr(agent, "name", None)

            # Decrement delegation depth as agent completes
            current_depth = decrement_delegation_depth()

            event = create_event(
                event_type="agent_end",
                agent_name=agent_name,
                framework="adk",
                delegation_depth=current_depth,
            )
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in after_agent_callback: {e}", exc_info=True)
        return None

    async def before_model_callback(self, *, callback_context, llm_request) -> None:
        """Capture before_model event.

        Args:
            callback_context: ADK callback context
            llm_request: LLM request object

        Returns:
            None (observation mode)
        """
        try:
            _turn_start_var.set(time.monotonic())

            # Extract model name from llm_request and store for after_model
            model_name = None
            if llm_request is not None:
                model_name = getattr(llm_request, "model", None)
            _last_model_name_var.set(model_name)

            event = create_event(
                event_type="model_request",
                model_name=model_name,
                framework="adk",
            )
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in before_model_callback: {e}", exc_info=True)
        return None

    async def after_model_callback(self, *, callback_context, llm_response) -> None:
        """Capture after_model event with token extraction, cost tracking, and velocity.

        Extracts token counts from llm_response.usage_metadata (when available),
        calculates cost via CostCalculator, accumulates session cost, tracks token
        velocity, and emits cost_threshold_exceeded event when threshold is crossed.

        Args:
            callback_context: ADK callback context
            llm_response: LLM response object with optional usage_metadata

        Returns:
            None (observation mode)
        """
        try:
            # Extract model name: prefer request model (from before_model), fall back to response
            model_name = _last_model_name_var.get()
            if model_name is None and llm_response is not None:
                model_name = getattr(llm_response, "model_version", None) or getattr(llm_response, "model", None)

            # Extract usage_metadata if available
            usage_metadata = getattr(llm_response, "usage_metadata", None) if llm_response else None
            tokens = normalize_adk_tokens(usage_metadata)

            if tokens is not None:
                input_tokens = tokens.input_tokens
                output_tokens = tokens.output_tokens
                total_tokens = tokens.total_tokens

                # Calculate cost for this call
                # CostCalculator expects int for cached_tokens, not Optional[int]
                cost = self._cost_calculator.calculate_cost(
                    model_name or "unknown", input_tokens, output_tokens, tokens.cached_tokens or 0
                )

                # Accumulate session cost
                session_total = add_to_session_cost(cost)

                # Track token velocity
                tokens_per_minute = record_token_usage(total_tokens)

                # Check threshold and emit alert (once per session)
                if (
                    self._cost_threshold is not None
                    and not _threshold_exceeded_var.get()
                    and session_total >= self._cost_threshold
                ):
                    _threshold_exceeded_var.set(True)
                    threshold_event = create_event(
                        event_type="cost_threshold_exceeded",
                        framework="adk",
                        session_cost_usd=float(session_total),
                        threshold_usd=float(self._cost_threshold),
                        exceeded=True,
                        message=f"Session cost ${session_total:.6f} exceeded threshold ${self._cost_threshold:.2f}",
                    )
                    self._emit_event(threshold_event)

                event = create_event(
                    event_type="model_response",
                    model_name=model_name,
                    framework="adk",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=tokens.cached_tokens,
                    reasoning_tokens=tokens.reasoning_tokens,
                    total_tokens=total_tokens,
                    cost_usd=float(cost),
                    session_cost_usd=float(session_total),
                    tokens_per_minute=float(tokens_per_minute),
                )
                self._emit_event(event)
            else:
                # No usage_metadata available (streaming or non-Gemini model)
                # Emit basic after_model event without token/cost data
                event = create_event(
                    event_type="model_response",
                    model_name=model_name,
                    framework="adk",
                )
                self._emit_event(event)

            # Emit turn_duration with elapsed wall time
            turn_start = _turn_start_var.get(None)
            if turn_start is not None:
                _turn_start_var.set(None)
                duration_ms = round((time.monotonic() - turn_start) * 1000, 2)
                duration_event = create_event(
                    event_type="turn_duration",
                    model_name=model_name,
                    framework="adk",
                    duration_ms=duration_ms,
                )
                self._emit_event(duration_event)

        except Exception as e:
            logger.error(f"Telemetry error in after_model_callback: {e}", exc_info=True)
        return None

    async def on_model_error_callback(self, *, callback_context, llm_request, error) -> None:
        """Capture model error event with error classification.

        Args:
            callback_context: ADK callback context
            llm_request: LLM request object
            error: Exception that occurred

        Returns:
            None (observation mode)
        """
        try:
            # Emit turn_duration even for failed calls (valuable for timeout analysis)
            model_name = _last_model_name_var.get()
            turn_start = _turn_start_var.get(None)
            if turn_start is not None:
                _turn_start_var.set(None)
                duration_ms = round((time.monotonic() - turn_start) * 1000, 2)
                duration_event = create_event(
                    event_type="turn_duration",
                    model_name=model_name,
                    framework="adk",
                    duration_ms=duration_ms,
                )
                self._emit_event(duration_event)

            # Classify error with retryability detection
            error_class, is_retryable = classify_error(error, context="model")
            error_type_name = type(error).__name__ if error else None
            error_message = str(error) if error else None

            event = create_event(
                event_type="model_error",
                framework="adk",
                error_class=error_class,
                is_retryable=is_retryable,
                error_type_name=error_type_name,
                error_message=error_message,
            )
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in on_model_error_callback: {e}", exc_info=True)
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> None:
        """Capture before_tool event and create tool span with sequence tracking.

        SPECIAL: Creates new span for tool-level operation tracking and records
        tool call sequence. When capture_tool_data is enabled, tool arguments
        are included in the event (redacted via cold path).

        Args:
            tool: ADK tool instance
            tool_args: Tool arguments
            tool_context: ADK tool context

        Returns:
            None (observation mode)
        """
        try:
            # Create new span for tool-level operation
            new_span()

            tool_name = getattr(tool, "name", None)
            tool_type = _get_tool_type(tool)

            # Record tool call — returns full sequence INCLUDING this call (tuples of (name, ts))
            raw_sequence = record_tool_call(tool_name) if tool_name else []
            # Build sequence payload (truncation + transform). Reuse record_tool_call return value
            # directly; calling get_tool_sequence() here would make a redundant copy of the same list.
            seq_payload = self._get_sequence_payload(raw_sequence)

            # Build event kwargs
            event_kwargs = dict(
                event_type="tool_start",
                tool_name=tool_name,
                framework="adk",
                tool_type=tool_type,
                **seq_payload,
            )

            # Opt-in: capture tool arguments (redacted via cold path)
            if self._capture_tool_data and tool_args:
                event_kwargs["tool_args"] = _safe_serialize(tool_args)

            event = create_event(**event_kwargs)
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in before_tool_callback: {e}", exc_info=True)
        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> None:
        """Capture after_tool event.

        When capture_tool_data is enabled, tool arguments and result are
        included in the event (redacted via cold path).

        Args:
            tool: ADK tool instance
            tool_args: Tool arguments
            tool_context: ADK tool context
            result: Tool execution result

        Returns:
            None (observation mode)
        """
        try:
            tool_name = getattr(tool, "name", None)
            tool_type = _get_tool_type(tool)

            # Read sequence without recording (tool already recorded in before_tool_callback)
            raw_sequence = get_tool_sequence()
            seq_payload = self._get_sequence_payload(raw_sequence)

            event_kwargs = dict(
                event_type="tool_end",
                tool_name=tool_name,
                framework="adk",
                tool_type=tool_type,
                **seq_payload,
            )

            # Opt-in: capture tool arguments and result (redacted via cold path)
            if self._capture_tool_data:
                if tool_args:
                    event_kwargs["tool_args"] = _safe_serialize(tool_args)
                if result is not None:
                    event_kwargs["tool_result"] = _safe_serialize(result)

            event = create_event(**event_kwargs)
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in after_tool_callback: {e}", exc_info=True)
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error) -> None:
        """Capture tool error event with error classification.

        When capture_tool_data is enabled, tool arguments are included
        to help debug what input caused the error.

        Args:
            tool: ADK tool instance
            tool_args: Tool arguments
            tool_context: ADK tool context
            error: Exception that occurred

        Returns:
            None (observation mode)
        """
        try:
            tool_name = getattr(tool, "name", None)
            tool_type = _get_tool_type(tool)

            # Read sequence at error time — diagnose which pattern led to failure
            raw_sequence = get_tool_sequence()
            seq_payload = self._get_sequence_payload(raw_sequence)

            # Classify error with retryability detection
            error_class, is_retryable = classify_error(error, context="tool")
            error_type_name = type(error).__name__ if error else None
            error_message = str(error) if error else None

            event_kwargs = dict(
                event_type="tool_error",
                tool_name=tool_name,
                framework="adk",
                tool_type=tool_type,
                error_class=error_class,
                is_retryable=is_retryable,
                error_type_name=error_type_name,
                error_message=error_message,
                **seq_payload,
            )

            # Opt-in: capture tool arguments that caused the error
            if self._capture_tool_data and tool_args:
                event_kwargs["tool_args"] = _safe_serialize(tool_args)

            event = create_event(**event_kwargs)
            self._emit_event(event)
        except Exception as e:
            logger.error(f"Telemetry error in on_tool_error_callback: {e}", exc_info=True)
        return None

    async def on_event_callback(self, *, invocation_context, event) -> None:
        """Capture streaming event.

        Skips partial streaming chunks to avoid event flood during SSE.
        Only captures complete events that represent finalized state.

        Args:
            invocation_context: ADK invocation context
            event: ADK event object

        Returns:
            None (observation mode)
        """
        try:
            # Skip partial streaming chunks — these fire for every SSE fragment
            # and would flood telemetry storage with noise
            if getattr(event, "partial", None) is True:
                return None

            event_data = None
            if event is not None:
                event_data = {"event_type": type(event).__name__}

            telemetry_event = create_event(
                event_type="stream_event",
                framework="adk",
                data=event_data,
            )
            self._emit_event(telemetry_event)
        except Exception as e:
            logger.error(f"Telemetry error in on_event_callback: {e}", exc_info=True)
        return None

    async def close(self) -> None:
        """Cleanup telemetry plugin on shutdown.

        Logs summary of captured events. Shutdown is handled by
        BackgroundWorker's atexit handler in Phase 2.

        Returns:
            None
        """
        try:
            # Emit close event
            event = create_event(event_type="adapter_close", framework="adk")
            self._emit_event(event)

            # Log summary
            if self._queue is not None:
                stats = self._queue.get_stats()
                logger.info(f"TelemetryPlugin closing. Enqueued: {stats['enqueued']}, Dropped: {stats['dropped']}")
            else:
                event_count = len(self._events)
                logger.info(f"TelemetryPlugin closing. Captured {event_count} events.")
        except Exception as e:
            logger.error(f"Telemetry error in close: {e}", exc_info=True)
