"""PydanticAIAdapter: Pydantic AI adapter for agent telemetry via OTel SpanProcessor bridge.

Implements SpanProcessor from opentelemetry.sdk.trace and satisfies the
FrameworkAdapter Protocol. Receives completed OTel spans from pydantic-ai's
InstrumentedModel (enabled via Agent.instrument_all() or per-agent instrument=
parameter) and translates them into TelemetryEvents:

    "chat {model_name}" span     -> model_response event (with token/cost data)
    "running tool" span (v2)     -> tool_call event (with tool name)
    "execute_tool *" span (v3+)  -> tool_call event (with tool name)

Observation-only guarantee: on_end() never raises — all exceptions caught internally
so agent execution is never disrupted by telemetry errors.

IMPORTANT: Agent.instrument_all() MUST be called before any agent runs for spans
to be emitted. This adapter only processes spans — it does not emit them.

Usage::

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import set_tracer_provider
    from pydantic_ai import Agent

    from aba_telemetry.adapters.pydantic_ai import PydanticAIAdapter

    provider = TracerProvider()
    adapter = PydanticAIAdapter(capture_tool_data=True)
    provider.add_span_processor(adapter)
    set_tracer_provider(provider)

    Agent.instrument_all()  # MUST call before agent runs

    agent = Agent("openai:gpt-4o")
    result = agent.run_sync("Hello")
    events = adapter.events  # captured TelemetryEvent list
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from opentelemetry.sdk.trace import SpanProcessor

from aba_telemetry.core.events import create_event, TelemetryEvent
from aba_telemetry.core.cost import CostCalculator
from aba_telemetry.core.dedup import register_emission
from aba_telemetry.adapters.utils import NormalizedTokens, safe_serialize

logger = logging.getLogger(__name__)


class PydanticAIAdapter(SpanProcessor):
    """Pydantic AI adapter that captures model and tool calls via OTel SpanProcessor bridge.

    Subclasses SpanProcessor from opentelemetry.sdk.trace and satisfies the
    FrameworkAdapter Protocol:
        - framework_name property returns "pydantic-ai"
        - emit() routes events to queue or in-memory list
        - get_adapter_stats() returns error/drop counters
        - events property returns copy of internal event list

    Receives completed OTel spans from pydantic-ai's InstrumentedModel. The adapter
    is a downstream consumer of these spans — not a parallel hook. Using both
    Agent.instrument_all() AND the adapter together is correct: instrument_all()
    generates the spans; this adapter reads them. No double-counting occurs because
    the adapter never independently intercepts model calls.

    Span routing in on_end():
        - name.startswith("chat ")            -> _handle_model_span()  -> model_response
        - name == "running tool"              -> _handle_tool_span()   -> tool_call (v2)
        - name.startswith("execute_tool ")    -> _handle_tool_span()   -> tool_call (v3+)
        - all other spans (agent run, etc.)   -> silently skipped

    Observation-only guarantee: on_end() never raises.

    Usage::

        provider = TracerProvider()
        adapter = PydanticAIAdapter(capture_tool_data=True)
        provider.add_span_processor(adapter)
        set_tracer_provider(provider)

        Agent.instrument_all()

        agent = Agent("openai:gpt-4o")
        result = agent.run_sync("Hello")
        events = adapter.events
    """

    def __init__(
        self,
        queue=None,
        cost_calculator: Optional[CostCalculator] = None,
        cost_threshold_usd=None,
        capture_tool_data: bool = False,
        payload_max_bytes: int = 4096,
    ) -> None:
        """Initialize PydanticAIAdapter.

        Args:
            queue: Optional DropOldestQueue for async event processing.
                   If None, events are stored in-memory (Phase 1 behavior).
            cost_calculator: Optional CostCalculator with pricing data.
                             If None, creates one from co-located pricing.json
                             (covers OpenAI, Anthropic, and Gemini models).
            cost_threshold_usd: Optional cost threshold in USD. When a model call's
                                 cost >= threshold, emits cost_threshold_exceeded event
                                 (once per adapter lifetime).
            capture_tool_data: If True, serialize tool parameters into events.
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

        # Initialize cost calculator with multi-provider pricing (OpenAI, Anthropic, Gemini)
        if cost_calculator is not None:
            self._cost_calculator = cost_calculator
        else:
            pricing_path = Path(__file__).parent / "pricing.json"
            self._cost_calculator = CostCalculator(str(pricing_path))

        logger.debug(
            f"PydanticAIAdapter initialized (queue={'async' if queue else 'in-memory'}, "
            f"threshold={'$' + str(cost_threshold_usd) if cost_threshold_usd else 'none'}, "
            f"capture_tool_data={capture_tool_data})"
        )

    # ========================================================================
    # FrameworkAdapter Protocol
    # ========================================================================

    @property
    def framework_name(self) -> str:
        """Return the framework identifier for this adapter."""
        return "pydantic-ai"

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
    # SpanProcessor interface
    # ========================================================================

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        """No-op — we only process completed spans in on_end.

        Args:
            span: The span that is starting (not used)
            parent_context: Optional parent context (not used)
        """
        pass

    def on_end(self, span: Any) -> None:
        """Called synchronously when a span ends. Routes by span name.

        Extracts span name and attributes safely. Routes:
            - "chat {model_name}" spans to _handle_model_span()
            - "running tool" (v2) or "execute_tool *" (v3+) to _handle_tool_span()
            - All other spans (agent run, invoke_agent, etc.) are silently skipped.

        Observation-only guarantee: entire method body wrapped in try/except Exception.
        On any error, _error_count is incremented and error is logged.

        Args:
            span: ReadableSpan from opentelemetry.sdk.trace (type-annotated as Any
                  to avoid hard dependency at call sites outside the [pydantic-ai] extra)
        """
        try:
            name = getattr(span, "name", "") or ""
            attrs = dict(span.attributes) if getattr(span, "attributes", None) else {}

            if name.startswith("chat "):
                self._handle_model_span(name, attrs)
            elif name == "running tool" or name.startswith("execute_tool "):
                self._handle_tool_span(name, attrs)
            # Other spans (agent run, invoke_agent, running tools group, etc.): skip silently
        except Exception as e:
            self._error_count += 1
            logger.error(f"PydanticAIAdapter error in on_end: {e}", exc_info=True)

    def shutdown(self) -> None:
        """Log adapter stats at shutdown.

        Called when the TracerProvider is shut down. Logs final adapter stats
        for observability. Does not raise.
        """
        logger.info(f"PydanticAIAdapter shutdown: {self.get_adapter_stats()}")

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        """No-op — in-memory storage is synchronous.

        All events are stored synchronously in on_end(), so there is nothing to
        flush. Returns True to indicate success.

        Args:
            timeout_millis: Timeout in milliseconds (ignored)

        Returns:
            True (always succeeds)
        """
        return True

    # ========================================================================
    # Private span handlers
    # ========================================================================

    def _handle_model_span(self, name: str, attrs: dict) -> None:
        """Extract token usage and cost from a 'chat {model}' span and emit model_response.

        Token extraction is simpler than LangChain: pydantic-ai delivers token counts
        as flat int attributes directly on the span. No nested structure to navigate.

        Model name normalization: strips provider prefix if present so "openai:gpt-4o"
        becomes "gpt-4o" for pricing.json lookup.

        Args:
            name: Span name (e.g., "chat gpt-4o")
            attrs: Span attributes dict (from span.attributes)
        """
        try:
            # Model name: prefer response model (actual) over request model (requested)
            model_name = (
                attrs.get("gen_ai.response.model")
                or attrs.get("gen_ai.request.model")
                or "unknown"
            )

            # Strip provider prefix if present: "openai:gpt-4o" -> "gpt-4o"
            # Handles pydantic-ai provider string format where model is "provider:name"
            if ":" in model_name:
                model_name = model_name.split(":", 1)[1]

            # Token extraction: flat attributes, int coercion handles None and 0
            input_tokens = int(attrs.get("gen_ai.usage.input_tokens", 0) or 0)
            output_tokens = int(attrs.get("gen_ai.usage.output_tokens", 0) or 0)

            # Cached tokens: optional, use None sentinel if not present
            cached_tokens_raw = attrs.get("gen_ai.usage.details.cache_read_tokens")
            cached_tokens = int(cached_tokens_raw) if cached_tokens_raw else None

            # Build NormalizedTokens only if we have actual token data
            tokens: Optional[NormalizedTokens] = None
            if input_tokens or output_tokens:
                tokens = NormalizedTokens(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cached_tokens=cached_tokens,
                    reasoning_tokens=None,  # Not exposed in pydantic-ai v1.x spans
                )

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
                    framework="pydantic-ai",
                    cost_usd=float(cost),
                    input_tokens=tokens.input_tokens,
                    output_tokens=tokens.output_tokens,
                    total_tokens=tokens.total_tokens,
                )

                if tokens.cached_tokens is not None:
                    event_kwargs["cached_tokens"] = tokens.cached_tokens
            else:
                # No usage data available: emit event without token/cost fields
                cost = None
                event_kwargs = dict(
                    event_type="model_response",
                    model_name=model_name,
                    framework="pydantic-ai",
                )

            event = create_event(**event_kwargs)
            self.emit(event)

            # Emit cost_threshold_exceeded if threshold crossed (once per adapter lifetime)
            if (
                cost is not None
                and self._cost_threshold is not None
                and float(cost) >= float(self._cost_threshold)
                and not self._cost_threshold_emitted
            ):
                self._cost_threshold_emitted = True
                threshold_event = create_event(
                    event_type="cost_threshold_exceeded",
                    framework="pydantic-ai",
                    session_cost_usd=float(cost),
                    threshold_usd=float(self._cost_threshold),
                    exceeded=True,
                )
                self.emit(threshold_event)

        except Exception as e:
            self._error_count += 1
            logger.error(f"PydanticAIAdapter error in _handle_model_span: {e}", exc_info=True)

    def _handle_tool_span(self, name: str, attrs: dict) -> None:
        """Extract tool name and emit tool_call event from a tool span.

        Supports both v2 ("running tool" with gen_ai.tool.name attribute) and
        v3+ ("execute_tool {name}" with gen_ai.tool.name attribute). Tool name
        is extracted from the attribute first; falls back to parsing span name
        for execute_tool spans.

        Args:
            name: Span name (e.g., "running tool" or "execute_tool calculator")
            attrs: Span attributes dict (from span.attributes)
        """
        try:
            # Tool name: attribute takes priority over name parsing
            # v2: gen_ai.tool.name attribute is set
            # v3+: gen_ai.tool.name attribute is still set; name also contains tool name
            tool_name = (
                attrs.get("gen_ai.tool.name")
                or (name.split(" ", 1)[1] if name.startswith("execute_tool ") else None)
                or "unknown"
            )

            event_kwargs: dict[str, Any] = dict(
                event_type="tool_end",
                tool_name=tool_name,
                framework="pydantic-ai",
            )

            if self._capture_tool_data:
                # v3+: gen_ai.tool.call.arguments (preferred, OTel GenAI convention)
                # v2:  gen_ai.tool.parameters (older attribute name)
                params = (
                    attrs.get("gen_ai.tool.call.arguments")
                    or attrs.get("gen_ai.tool.parameters")
                )
                if params:
                    event_kwargs["tool_args"] = safe_serialize(params, self._payload_max_bytes)

            event = create_event(**event_kwargs)
            self.emit(event)

        except Exception as e:
            self._error_count += 1
            logger.error(f"PydanticAIAdapter error in _handle_tool_span: {e}", exc_info=True)
