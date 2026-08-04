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
from typing import Optional

from litellm.integrations.custom_logger import CustomLogger

from observra.core.context import initialize_session, initialize_trace
from observra.core.dedup import reset_dedup
from observra.core.events import TelemetryEvent

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

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on successful completion (sync)."""
        # TODO: implement
        pass

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on failed completion (sync)."""
        # TODO: implement
        pass

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on successful completion (async)."""
        # TODO: implement
        pass

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Called by LiteLLM on failed completion (async)."""
        # TODO: implement
        pass

    def get_adapter_stats(self) -> dict:
        return {
            "framework": "litellm",
            "error_count": self._error_count,
            "events_captured": self._events_captured,
        }
