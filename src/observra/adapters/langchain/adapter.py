# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""LangChainAdapter: LangChain/LangGraph adapter for agent telemetry.

Implements BaseCallbackHandler from langchain-core and satisfies the
FrameworkAdapter Protocol. Intercepts LLM, tool, and chain lifecycle events
and maps them to TelemetryEvents:

    on_chat_model_start  -> captures model name by run_id (no event)
    on_llm_start         -> captures model name by run_id (no event, legacy LLMs)
    on_llm_end           -> model_response with token extraction via normalize_langchain_tokens()
    on_llm_new_token     -> intentional no-op (streaming deduplication: only on_llm_end emits)
    on_tool_start        -> tool_call event with run_id correlation for duration tracking
    on_tool_end          -> tool_call_end event with duration_ms computed from run_id
    on_tool_error        -> tool_error event with error details
    on_chain_start       -> chain_start event; initializes trace context if top-level chain
    on_chain_end         -> chain_end event
    on_chain_error       -> chain_end event with error details

Observation-only guarantee: every callback catches all exceptions internally so the
LangChain/LangGraph run is never disrupted by telemetry errors.

Token extraction is provider-agnostic via normalize_langchain_tokens():
priority order: usage_metadata (modern) > llm_output["token_usage"] (OpenAI legacy)
> llm_output["usage"] (Anthropic).

Usage::

    adapter = LangChainAdapter(capture_tool_data=True)
    result = graph.invoke(
        {"messages": [HumanMessage(content="Hello")]},
        config={"callbacks": [adapter]},
    )
    events = adapter.events  # captured TelemetryEvent list
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.callbacks.base import BaseCallbackHandler

from observra.adapters.utils import normalize_langchain_tokens, safe_serialize
from observra.core.context import initialize_session, initialize_trace
from observra.core.cost import CostCalculator
from observra.core.dedup import register_emission, reset_dedup
from observra.core.events import TelemetryEvent, create_event

logger = logging.getLogger(__name__)


class LangChainAdapter(BaseCallbackHandler):
    """LangChain/LangGraph adapter that captures all LLM, tool, and chain events.

    Subclasses BaseCallbackHandler from langchain-core and satisfies the
    FrameworkAdapter Protocol:
        - framework_name property returns "langgraph"
        - emit() routes events to queue or in-memory list
        - get_adapter_stats() returns error/drop counters

    All callbacks are synchronous (compatible with both sync and async LangGraph).
    Token extraction is provider-agnostic via normalize_langchain_tokens().
    on_llm_new_token is intentionally a no-op (streaming deduplication).

    Usage::

        adapter = LangChainAdapter(capture_tool_data=True)
        result = graph.invoke(
            {"messages": [...]},
            config={"callbacks": [adapter]},
        )
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
        """Initialize LangChainAdapter.

        Args:
            queue: Optional DropOldestQueue for async event processing.
                   If None, events are stored in-memory (Phase 1 behavior).
            cost_calculator: Optional CostCalculator with LangChain pricing.
                             If None, creates one from co-located pricing.json.
            cost_threshold_usd: Optional cost threshold in USD. When an LLM call's
                                 cost >= threshold, emits cost_threshold_exceeded event
                                 (once per adapter lifetime).
            capture_tool_data: If True, serialize tool args and results into events.
                                Default False for privacy.
            payload_max_bytes: Max bytes for tool data serialization (default 4096).
        """
        super().__init__()
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

        # Tool duration tracking: str(run_id) -> (tool_name, start_time_monotonic)
        self._tool_starts: dict[str, tuple[str, float]] = {}

        # Model name capture: str(run_id) -> model_name (from on_chat_model_start/on_llm_start)
        self._model_names: dict[str, str] = {}

        # Initialize cost calculator with LangChain multi-provider pricing
        if cost_calculator is not None:
            self._cost_calculator = cost_calculator
        else:
            pricing_path = Path(__file__).parent / "pricing.json"
            self._cost_calculator = CostCalculator(str(pricing_path))

        logger.debug(
            f"LangChainAdapter initialized (queue={'async' if queue else 'in-memory'}, "
            f"threshold={'$' + str(cost_threshold_usd) if cost_threshold_usd else 'none'}, "
            f"capture_tool_data={capture_tool_data})"
        )

    # ========================================================================
    # FrameworkAdapter Protocol
    # ========================================================================

    @property
    def framework_name(self) -> str:
        """Return the framework identifier for this adapter."""
        return "langgraph"

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
    # BaseCallbackHandler — LLM callbacks
    # ========================================================================

    def on_chat_model_start(self, serialized: dict, messages: list, *, run_id: Any, **kwargs: Any) -> None:
        """Capture model name from chat model start for use in on_llm_end.

        Chat models (ChatOpenAI, ChatAnthropic, etc.) fire this callback instead
        of on_llm_start. Stores model name by run_id — no event emitted here.

        Args:
            serialized: LangChain serialized model dict with kwargs.model_name
            messages: List of message batches (not used)
            run_id: UUID identifying this LLM call (same run_id arrives in on_llm_end)
        """
        try:
            model_name = (
                serialized.get("kwargs", {}).get("model_name")
                or serialized.get("kwargs", {}).get("model")
                or serialized.get("id", ["unknown"])[-1]
                or "unknown"
            )
            self._model_names[str(run_id)] = model_name
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_chat_model_start: {e}", exc_info=True)

    def on_llm_start(self, serialized: dict, prompts: list, *, run_id: Any, **kwargs: Any) -> None:
        """Capture model name from legacy LLM start for use in on_llm_end.

        Legacy completion-API LLMs fire this callback. Chat models fire
        on_chat_model_start instead. Stores model name by run_id — no event emitted.

        Args:
            serialized: LangChain serialized model dict with kwargs.model_name
            prompts: List of prompt strings (not used)
            run_id: UUID identifying this LLM call (same run_id arrives in on_llm_end)
        """
        try:
            model_name = (
                serialized.get("kwargs", {}).get("model_name")
                or serialized.get("kwargs", {}).get("model")
                or serialized.get("id", ["unknown"])[-1]
                or "unknown"
            )
            self._model_names[str(run_id)] = model_name
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_llm_start: {e}", exc_info=True)

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        """Emit model_response event with provider-agnostic token extraction.

        Calls normalize_langchain_tokens() to extract tokens from all 3 paths
        (usage_metadata > llm_output["token_usage"] > llm_output["usage"]).
        Retrieves model name captured in on_chat_model_start/on_llm_start.
        Computes cost via CostCalculator. Checks cost threshold (once per lifetime).

        Args:
            response: LLMResult from LangChain with generations and llm_output
            run_id: UUID matching the on_chat_model_start/on_llm_start call
        """
        try:
            tokens = normalize_langchain_tokens(response)

            # Retrieve model name captured at start; fall back to llm_output or unknown
            model_name = self._model_names.pop(str(run_id), None)
            if model_name is None:
                llm_output = getattr(response, "llm_output", None) or {}
                model_name = llm_output.get("model_name") or "unknown"

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
                    framework="langgraph",
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
                    framework="langgraph",
                )

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
                    framework="langgraph",
                    session_cost_usd=float(cost),
                    threshold_usd=float(self._cost_threshold),
                    exceeded=True,
                )
                self.emit(threshold_event)

        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_llm_end: {e}", exc_info=True)

    def on_llm_new_token(self, token: str, *, chunk: Any = None, run_id: Any, **kwargs: Any) -> None:
        """Intentional no-op for streaming chunk events.

        Streaming deduplication: LangChain fires on_llm_new_token once per chunk
        (each chunk has partial/no token counts). on_llm_end fires exactly once
        per LLM call with the final LLMResult and complete token counts.

        Only on_llm_end emits events — this prevents duplicate/inflated events
        during streaming (success criterion 3).
        """
        pass

    # ========================================================================
    # BaseCallbackHandler — tool callbacks
    # ========================================================================

    def on_tool_start(self, serialized: dict, input_str: str, *, run_id: Any, **kwargs: Any) -> None:
        """Emit tool_call event and record start time for duration computation.

        Stores (tool_name, start_time) by run_id for correlation in on_tool_end.

        Args:
            serialized: LangChain serialized tool dict with name
            input_str: Tool input as string (serialized)
            run_id: UUID for this tool invocation
        """
        try:
            serialized = serialized or {}
            tool_name = serialized.get("name") or "unknown"
            self._tool_starts[str(run_id)] = (tool_name, time.monotonic())

            event_kwargs: dict[str, Any] = dict(
                event_type="tool_start",
                tool_name=tool_name,
                framework="langgraph",
            )

            if self._capture_tool_data and input_str:
                event_kwargs["tool_args"] = safe_serialize(input_str, self._payload_max_bytes)

            event = create_event(**event_kwargs)
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_tool_start: {e}", exc_info=True)

    def on_tool_end(self, output: Any, *, run_id: Any, **kwargs: Any) -> None:
        """Emit tool_call_end event with duration_ms computed from run_id correlation.

        Pops start info from _tool_starts using str(run_id) to handle UUID type
        inconsistencies across sync/async callback paths.

        Args:
            output: Tool result (any type)
            run_id: UUID matching the on_tool_start call
        """
        try:
            start_info = self._tool_starts.pop(str(run_id), None)
            tool_name = start_info[0] if start_info else "unknown"
            duration_ms = (time.monotonic() - start_info[1]) * 1000.0 if start_info else None

            event_kwargs: dict[str, Any] = dict(
                event_type="tool_end",
                tool_name=tool_name,
                framework="langgraph",
            )

            if duration_ms is not None:
                event_kwargs["duration_ms"] = duration_ms

            if self._capture_tool_data and output is not None:
                event_kwargs["tool_result"] = safe_serialize(output, self._payload_max_bytes)

            event = create_event(**event_kwargs)
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_tool_end: {e}", exc_info=True)

    def on_tool_error(self, error: Any, *, run_id: Any, **kwargs: Any) -> None:
        """Emit tool_error event when a tool raises an exception.

        Pops start info from _tool_starts to clean up tracking state.

        Args:
            error: Exception or error object from the tool invocation
            run_id: UUID matching the on_tool_start call
        """
        try:
            start_info = self._tool_starts.pop(str(run_id), None)
            tool_name = start_info[0] if start_info else "unknown"

            event = create_event(
                event_type="tool_error",
                tool_name=tool_name,
                error_message=str(error),
                error_type_name=type(error).__name__,
                framework="langgraph",
            )
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_tool_error: {e}", exc_info=True)

    # ========================================================================
    # BaseCallbackHandler — chain callbacks
    # ========================================================================

    def on_chain_start(
        self,
        serialized: dict,
        inputs: dict,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Emit chain_start event and initialize session context for top-level chain.

        When parent_run_id is None, this is the top-level graph invocation.
        Initializes trace and session context vars so all nested events share
        the same trace_id/session_id.

        Args:
            serialized: LangChain serialized chain dict with name/id
            inputs: Chain input data (not captured — may contain user content)
            run_id: UUID for this chain invocation
            parent_run_id: UUID of parent chain, or None if top-level
        """
        try:
            serialized = serialized or {}
            chain_name = serialized.get("name") or serialized.get("id", ["unknown"])[-1] or "unknown"

            # Initialize trace context only for top-level graph invocation
            if parent_run_id is None:
                initialize_trace()
                initialize_session()
                reset_dedup()

            # Top-level chain = session_start, nested = agent_start
            event_type = "session_start" if parent_run_id is None else "agent_start"

            event = create_event(
                event_type=event_type,
                agent_name=chain_name,
                framework="langgraph",
            )
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_chain_start: {e}", exc_info=True)

    def on_chain_end(
        self,
        outputs: dict,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Emit session_end or agent_end event when chain completes successfully.

        Args:
            outputs: Chain output data (not captured — may contain model responses)
            run_id: UUID matching the on_chain_start call
            parent_run_id: UUID of parent chain, or None if top-level
        """
        try:
            event_type = "session_end" if parent_run_id is None else "agent_end"
            event = create_event(
                event_type=event_type,
                framework="langgraph",
            )
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_chain_end: {e}", exc_info=True)

    def on_chain_error(self, error: Any, *, run_id: Any, **kwargs: Any) -> None:
        """Emit session_end event with error details when chain raises an exception.

        Args:
            error: Exception or error object from the chain
            run_id: UUID matching the on_chain_start call
        """
        try:
            event = create_event(
                event_type="session_end",
                error_message=str(error),
                framework="langgraph",
            )
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.error(f"LangChainAdapter error in on_chain_error: {e}", exc_info=True)
