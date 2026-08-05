# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""LiteLLMAdapter: CustomLogger-based adapter for agent telemetry.

Implements LiteLLM's CustomLogger interface to capture model calls
across 100+ LLM providers. Registered via litellm.callbacks.

Usage:
    import observra
    observra.initialize(backend="jsonl")
    plugin = observra.create_plugin("litellm")
    # All litellm.completion() / acompletion() calls are now captured
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import litellm
from litellm.integrations.custom_logger import CustomLogger

from observra.core.context import initialize_session, initialize_trace
from observra.core.dedup import reset_dedup
from observra.core.events import TelemetryEvent, create_event
from observra.core.injection import detect_injection_patterns

logger = logging.getLogger(__name__)


class LiteLLMAdapter(CustomLogger):
    """LiteLLM CustomLogger that emits Observra telemetry events.

    Captures model_response and model_error events from all LiteLLM
    completion calls (sync, async, streaming). Uses LiteLLM's built-in
    completion_cost() for pricing across 100+ providers.

    Args:
        queue: Event queue proxy from observra.initialize().
        agent_name: Optional agent name for attribution.
        capture_content: If True, run injection detection on input messages.
    """

    def __init__(
        self,
        queue=None,
        agent_name: Optional[str] = None,
        capture_content: bool = False,
    ):
        self._queue = queue
        self._agent_name = agent_name
        self._capture_content = capture_content
        self._seeded = False
        self._error_count: int = 0
        self._events_captured: int = 0

    def _ensure_session(self) -> None:
        if not self._seeded:
            initialize_trace()
            initialize_session()
            reset_dedup()
            self._seeded = True

    def emit(self, event: TelemetryEvent) -> None:
        """Route event to the pipeline queue."""
        if self._queue is not None:
            self._queue.put_nowait(event)
            self._events_captured += 1

    def _calc_duration_ms(self, start_time, end_time) -> float:
        return (end_time - start_time).total_seconds() * 1000

    def _calc_cost(self, response_obj) -> Optional[float]:
        try:
            return float(litellm.completion_cost(completion_response=response_obj))
        except Exception:
            return None

    def _detect_injection(self, kwargs: dict) -> dict:
        if not self._capture_content:
            return {}
        messages = kwargs.get("messages", [])
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                patterns = detect_injection_patterns(content)
                if patterns:
                    return {"has_injection_patterns": True, "injection_patterns": patterns}
        return {}

    def _handle_success(self, kwargs: dict, response_obj: Any, start_time, end_time) -> None:
        try:
            self._ensure_session()

            model_name = getattr(response_obj, "model", None) or kwargs.get("model", "unknown")
            usage = getattr(response_obj, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

            data: dict[str, Any] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": self._calc_duration_ms(start_time, end_time),
            }

            cost = self._calc_cost(response_obj)
            if cost is not None:
                data["cost_usd"] = cost

            data.update(self._detect_injection(kwargs))

            event = create_event(
                event_type="model_response",
                model_name=model_name,
                agent_name=self._agent_name,
                framework="litellm",
                **data,
            )
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.warning(f"LiteLLMAdapter error in success handler: {e}")

    def _handle_failure(self, kwargs: dict, exception: Any, start_time, end_time) -> None:
        try:
            self._ensure_session()

            model_name = kwargs.get("model", "unknown")
            error_message = str(exception) if exception else "unknown error"

            data: dict[str, Any] = {
                "error_message": error_message,
                "duration_ms": self._calc_duration_ms(start_time, end_time),
            }

            event = create_event(
                event_type="model_error",
                model_name=model_name,
                agent_name=self._agent_name,
                framework="litellm",
                **data,
            )
            self.emit(event)
        except Exception as e:
            self._error_count += 1
            logger.warning(f"LiteLLMAdapter error in failure handler: {e}")

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on successful completion (sync)."""
        self._handle_success(kwargs, response_obj, start_time, end_time)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on failed completion (sync)."""
        self._handle_failure(kwargs, response_obj, start_time, end_time)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on successful completion (async)."""
        self._handle_success(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on failed completion (async)."""
        self._handle_failure(kwargs, response_obj, start_time, end_time)

    def get_adapter_stats(self) -> dict:
        return {
            "framework": "litellm",
            "error_count": self._error_count,
            "events_captured": self._events_captured,
        }
