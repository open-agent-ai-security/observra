"""ClaudeAdapter: Claude Agent SDK adapter for agent telemetry.

Implements the FrameworkAdapter Protocol for the Claude Agent SDK.
Hooks into PreToolUse, PostToolUse, UserPromptSubmit, Stop, and SubagentStop
events. Also provides wrap_stream() to emit model_response events for text
content blocks and session_end from the ResultMessage.

Observation-only guarantee: every hook callback returns {} and never raises.
Token costs are estimated via tiktoken (flagged estimated=True) since Claude
hooks fire around tool calls, not model calls. Exact costs are available from
ResultMessage.total_cost_usd when using wrap_stream() or handle_result_message().
"""

from __future__ import annotations

import logging
import time
import warnings
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from observra.adapters.utils import estimate_tokens, safe_serialize
from observra.core.cost import CostCalculator
from observra.core.dedup import register_emission
from observra.core.events import TelemetryEvent, create_event

logger = logging.getLogger(__name__)

# One-time startup warning flag — prevents re-emitting on each adapter instantiation
_startup_warned: bool = False


class ClaudeAdapter:
    """Claude Agent SDK adapter that captures 5 hook lifecycle events.

    Satisfies the FrameworkAdapter Protocol:
        - framework_name property returns "claude"
        - emit() routes events to queue or in-memory list
        - get_adapter_stats() returns error/drop counters

    Hook callbacks are observation-only: all 5 callbacks return {} (empty dict)
    so Claude SDK proceeds unchanged. Token counts are estimated via tiktoken
    and flagged estimated=True. Exact costs are sourced from ResultMessage when
    using wrap_stream() or handle_result_message().

    Usage::

        adapter = ClaudeAdapter(capture_tool_data=True)
        client = ClaudeSDKClient(options=adapter.get_hook_options())
        async for message in adapter.wrap_stream(client.stream(prompt)):
            handle_message(message)
    """

    def __init__(
        self,
        queue=None,
        cost_calculator: Optional[CostCalculator] = None,
        cost_threshold_usd: Optional[Decimal] = None,
        capture_tool_data: bool = False,
        payload_max_bytes: int = 4096,
    ) -> None:
        """Initialize ClaudeAdapter.

        Args:
            queue: Optional DropOldestQueue for async event processing.
                   If None, events are stored in-memory (Phase 1 behavior).
            cost_calculator: Optional CostCalculator with Claude pricing.
                             If None, creates one from co-located pricing.json.
            cost_threshold_usd: Optional cost threshold in USD. When
                                 ResultMessage.total_cost_usd >= threshold,
                                 emits cost_threshold_exceeded event (once).
            capture_tool_data: If True, serialize tool_input and tool_response
                                into events. Default False for privacy.
            payload_max_bytes: Max bytes for tool data serialization (default 4096).
        """
        global _startup_warned

        self._queue = queue
        self._events: list[TelemetryEvent] = []
        self._enabled: bool = True
        self._cost_threshold = cost_threshold_usd
        self._capture_tool_data = capture_tool_data
        self._payload_max_bytes = payload_max_bytes
        self._error_count: int = 0
        self._dropped_events: int = 0
        self._events_captured: int = 0

        # Duration tracking: tool_use_id -> start time (monotonic)
        self._tool_start_times: dict[str, float] = {}

        # Cost threshold deduplication: emit once per adapter lifetime
        self._cost_threshold_emitted: bool = False

        # Initialize cost calculator with Claude-specific pricing
        if cost_calculator is not None:
            self._cost_calculator = cost_calculator
        else:
            pricing_path = Path(__file__).parent / "pricing.json"
            self._cost_calculator = CostCalculator(str(pricing_path))

        # One-time startup warning about token estimation
        if not _startup_warned:
            _startup_warned = True
            warnings.warn(
                "Claude token counts are estimated — costs are approximate",
                stacklevel=2,
            )

        logger.debug(
            f"ClaudeAdapter initialized (queue={'async' if queue else 'in-memory'}, "
            f"threshold={'$' + str(cost_threshold_usd) if cost_threshold_usd else 'none'}, "
            f"capture_tool_data={capture_tool_data})"
        )

    # ========================================================================
    # FrameworkAdapter Protocol
    # ========================================================================

    @property
    def framework_name(self) -> str:
        """Return the framework identifier for this adapter."""
        return "claude"

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
    # Hook configuration
    # ========================================================================

    def get_hook_options(self):
        """Build ClaudeAgentOptions with all 5 hooks registered.

        Imports ClaudeAgentOptions and HookMatcher lazily to avoid ImportError
        on base installs without claude-agent-sdk.

        Returns:
            ClaudeAgentOptions instance with all 5 telemetry hooks registered.
        """
        # Lazy import — not at module top level to avoid ImportError on base install
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

        # hooks is a dict mapping hook name -> list[HookMatcher].
        # Each HookMatcher wraps a list of callback functions.
        options = ClaudeAgentOptions(
            hooks={
                "PreToolUse": [HookMatcher(hooks=[self._on_pre_tool_use])],
                "PostToolUse": [HookMatcher(hooks=[self._on_post_tool_use])],
                "UserPromptSubmit": [HookMatcher(hooks=[self._on_user_prompt_submit])],
                "Stop": [HookMatcher(hooks=[self._on_stop])],
                "SubagentStop": [HookMatcher(hooks=[self._on_subagent_stop])],
            }
        )
        return options

    # ========================================================================
    # Token extraction helpers
    # ========================================================================

    def _extract_tokens_or_estimate(self, input_data: dict, text: str) -> tuple[int, bool]:
        """Return (token_count, is_estimated) for the given input_data and text.

        First checks input_data for native token fields (future Claude SDK versions
        may expose these). Falls back to tiktoken estimation when not available.

        Args:
            input_data: Hook input data dict (may contain token fields)
            text: Text to estimate tokens for if native fields not available

        Returns:
            (token_count, is_estimated) — is_estimated=False means native count
        """
        # Check for native token fields (forward-compat: future SDK may provide these)
        native = input_data.get("input_tokens")
        if native is None:
            usage = input_data.get("usage", {})
            if isinstance(usage, dict):
                native = usage.get("input_tokens")

        if native is not None:
            try:
                return (int(native), False)
            except (TypeError, ValueError):
                pass

        # Fall back to tiktoken estimation
        count = estimate_tokens(text)
        return (count, True)

    # ========================================================================
    # 5 Hook Callbacks (all return {})
    # ========================================================================

    async def _on_pre_tool_use(
        self,
        input_data: dict,
        tool_use_id: str,
        context: Any,
    ) -> dict:
        """Hook: PreToolUse — emits before_tool event, records start time.

        Args:
            input_data: Hook input dict with tool_name, tool_input, etc.
            tool_use_id: Unique tool use identifier for duration correlation
            context: Claude SDK hook context

        Returns:
            {} (observation-only)
        """
        try:
            tool_name = input_data.get("tool_name")

            # Record start time for duration calculation in PostToolUse
            self._tool_start_times[tool_use_id] = time.monotonic()

            event_kwargs: dict[str, Any] = dict(
                event_type="tool_start",
                tool_name=tool_name,
                framework="claude",
            )

            if self._capture_tool_data:
                raw_input = input_data.get("tool_input")
                if raw_input is not None:
                    event_kwargs["tool_args"] = safe_serialize(raw_input, self._payload_max_bytes)

            event = create_event(**event_kwargs)
            self.emit(event)
        except Exception as e:
            logger.error(f"ClaudeAdapter error in _on_pre_tool_use: {e}", exc_info=True)
        return {}

    async def _on_post_tool_use(
        self,
        input_data: dict,
        tool_use_id: str,
        context: Any,
    ) -> dict:
        """Hook: PostToolUse — emits after_tool event with duration and estimated tokens.

        Args:
            input_data: Hook input dict with tool_name, tool_input, tool_response, etc.
            tool_use_id: Unique tool use identifier for duration correlation
            context: Claude SDK hook context

        Returns:
            {} (observation-only)
        """
        try:
            tool_name = input_data.get("tool_name")

            # Compute duration from pre-tool start time
            start_time = self._tool_start_times.pop(tool_use_id, None)
            duration_ms: Optional[float] = None
            if start_time is not None:
                duration_ms = (time.monotonic() - start_time) * 1000.0

            # Estimate tokens from combined input + response text
            raw_input = input_data.get("tool_input", "")
            raw_response = input_data.get("tool_response", "")
            combined_text = (
                safe_serialize(raw_input, self._payload_max_bytes)
                + " "
                + safe_serialize(raw_response, self._payload_max_bytes)
            )
            token_count, is_estimated = self._extract_tokens_or_estimate(input_data, combined_text)

            event_kwargs: dict[str, Any] = dict(
                event_type="tool_end",
                tool_name=tool_name,
                framework="claude",
                estimated=is_estimated,
            )

            if duration_ms is not None:
                event_kwargs["duration_ms"] = duration_ms

            if token_count:
                event_kwargs["input_tokens"] = token_count

            if self._capture_tool_data:
                if raw_input is not None:
                    event_kwargs["tool_args"] = safe_serialize(raw_input, self._payload_max_bytes)
                if raw_response is not None:
                    event_kwargs["tool_result"] = safe_serialize(raw_response, self._payload_max_bytes)

            event = create_event(**event_kwargs)
            self.emit(event)
        except Exception as e:
            logger.error(f"ClaudeAdapter error in _on_post_tool_use: {e}", exc_info=True)
        return {}

    async def _on_user_prompt_submit(
        self,
        input_data: dict,
        tool_use_id: str,
        context: Any,
    ) -> dict:
        """Hook: UserPromptSubmit — emits user_prompt event with estimated input tokens.

        Args:
            input_data: Hook input dict with prompt text
            tool_use_id: Hook invocation identifier (not a tool call ID here)
            context: Claude SDK hook context

        Returns:
            {} (observation-only)
        """
        try:
            prompt = input_data.get("prompt", "")
            token_count, is_estimated = self._extract_tokens_or_estimate(input_data, prompt)

            event = create_event(
                event_type="user_message",
                framework="claude",
                user_message_text=prompt,
                input_tokens=token_count,
                estimated=is_estimated,
            )
            self.emit(event)
        except Exception as e:
            logger.error(f"ClaudeAdapter error in _on_user_prompt_submit: {e}", exc_info=True)
        return {}

    async def _on_stop(
        self,
        input_data: dict,
        tool_use_id: str,
        context: Any,
    ) -> dict:
        """Hook: Stop — emits agent_stop event.

        Args:
            input_data: Hook input dict with stop_hook_active flag
            tool_use_id: Hook invocation identifier
            context: Claude SDK hook context

        Returns:
            {} (observation-only)
        """
        try:
            event = create_event(
                event_type="agent_end",
                framework="claude",
                stop_hook_active=input_data.get("stop_hook_active"),
            )
            self.emit(event)
        except Exception as e:
            logger.error(f"ClaudeAdapter error in _on_stop: {e}", exc_info=True)
        return {}

    async def _on_subagent_stop(
        self,
        input_data: dict,
        tool_use_id: str,
        context: Any,
    ) -> dict:
        """Hook: SubagentStop — emits subagent_stop event.

        Args:
            input_data: Hook input dict with stop_hook_active and optional agent_id
            tool_use_id: Hook invocation identifier
            context: Claude SDK hook context

        Returns:
            {} (observation-only)
        """
        try:
            event = create_event(
                event_type="agent_end",
                framework="claude",
                stop_hook_active=input_data.get("stop_hook_active"),
                agent_id=input_data.get("agent_id"),
            )
            self.emit(event)
        except Exception as e:
            logger.error(f"ClaudeAdapter error in _on_subagent_stop: {e}", exc_info=True)
        return {}

    # ========================================================================
    # ResultMessage handling and stream wrapping
    # ========================================================================

    def handle_result_message(self, result_message: Any) -> None:
        """Emit session_end (and optionally cost_threshold_exceeded) from ResultMessage.

        Call this when you process the Claude SDK stream yourself and receive
        the final ResultMessage. When using wrap_stream(), this is called
        automatically — you do not need to call it separately.

        Args:
            result_message: Claude SDK ResultMessage with total_cost_usd and usage.
        """
        try:
            total_cost_usd = getattr(result_message, "total_cost_usd", None)
            num_turns = getattr(result_message, "num_turns", None)
            is_error = getattr(result_message, "is_error", None)
            session_id = getattr(result_message, "session_id", None)

            event_kwargs: dict[str, Any] = dict(
                event_type="session_end",
                framework="claude",
                estimated=False,
            )

            if total_cost_usd is not None:
                event_kwargs["session_cost_usd"] = float(total_cost_usd)

            if num_turns is not None:
                event_kwargs["num_turns"] = num_turns

            if is_error is not None:
                event_kwargs["is_error"] = is_error

            if session_id is not None:
                event_kwargs["session_id_claude"] = str(session_id)

            # Extract token usage if present on ResultMessage
            usage = getattr(result_message, "usage", None)
            if isinstance(usage, dict):
                for field_name in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                    val = usage.get(field_name)
                    if val is not None:
                        event_kwargs[field_name] = int(val)

            event = create_event(**event_kwargs)
            self.emit(event)

            # Emit cost_threshold_exceeded if threshold crossed (once per lifetime)
            if (
                self._cost_threshold is not None
                and total_cost_usd is not None
                and not self._cost_threshold_emitted
                and float(total_cost_usd) >= float(self._cost_threshold)
            ):
                self._cost_threshold_emitted = True
                threshold_event = create_event(
                    event_type="cost_threshold_exceeded",
                    framework="claude",
                    session_cost_usd=float(total_cost_usd),
                    threshold_usd=float(self._cost_threshold),
                    exceeded=True,
                    estimated=False,
                    message=(
                        f"Session cost ${float(total_cost_usd):.4f} exceeded "
                        f"threshold ${float(self._cost_threshold):.4f}"
                    ),
                )
                self.emit(threshold_event)

        except Exception as e:
            logger.error(f"ClaudeAdapter error in handle_result_message: {e}", exc_info=True)

    async def wrap_stream(self, stream):
        """Async generator that wraps ClaudeSDKClient message stream transparently.

        Emits model_response events for text content blocks (fulfilling the locked
        decision: emit events for model text responses even though token counts won't
        be available — useful for audit/replay). Emits session_end from ResultMessage.

        Observation-only: yields every message unchanged so callers consume the
        stream exactly as they would without telemetry. Exceptions in telemetry
        are caught and logged; the stream is never interrupted.

        Usage::

            adapter = ClaudeAdapter(capture_tool_data=True)
            client = ClaudeSDKClient(options=adapter.get_hook_options())
            async for message in adapter.wrap_stream(client.stream(prompt)):
                handle_message(message)  # message is unchanged

        Args:
            stream: Async iterable from ClaudeSDKClient (e.g., client.stream(prompt))

        Yields:
            Every message from the original stream, unchanged.
        """
        async for message in stream:
            try:
                # Check for ResultMessage (final item) — duck-type via total_cost_usd attr
                if hasattr(message, "total_cost_usd"):
                    self.handle_result_message(message)
                else:
                    # Check for text content blocks in AssistantMessage
                    content = getattr(message, "content", None)
                    if content:
                        text_parts = []
                        for block in content:
                            block_type = getattr(block, "type", None)
                            if block_type == "text":
                                block_text = getattr(block, "text", "")
                                if block_text:
                                    text_parts.append(block_text)
                        if text_parts:
                            response_text = " ".join(text_parts)
                            truncated_text = safe_serialize(response_text, self._payload_max_bytes)
                            event = create_event(
                                event_type="model_response",
                                framework="claude",
                                response_text=truncated_text,
                                estimated=True,
                            )
                            self.emit(event)
            except Exception as e:
                # Never interrupt the stream for telemetry errors
                logger.error(
                    f"ClaudeAdapter error in wrap_stream (message not lost): {e}",
                    exc_info=True,
                )

            # Always yield the original message unchanged
            yield message
