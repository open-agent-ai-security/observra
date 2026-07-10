# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Observra — framework-agnostic telemetry for AI agents.

Observra captures what your agents do — model calls, tool use, cost, latency,
and errors — normalizes every event into a common schema (CIM), and routes it
to the backends you already use (JSONL, webhooks, OpenTelemetry, or a SIEM such
as Exabeam). Your agent code runs unmodified: framework adapters emit events
through a non-blocking background pipeline.

The public API is intentionally small:

- `initialize` — start the global pipeline and choose a backend.
- `create_plugin` — wire a framework adapter (ADK, Claude, OpenAI, LangChain,
  Pydantic AI) into that pipeline.
- `create_logging_handler` — capture standard-library logs as telemetry.
- `get_stats` / `get_metrics` — inspect pipeline health.

Example:
    ```python
    import observra

    # 1. Start the pipeline (newline-delimited JSON by default)
    observra.initialize(backend="jsonl", path="telemetry.jsonl")

    # 2. Attach the adapter for your agent framework
    plugin = observra.create_plugin("adk")

    # ...run your agent as usual; events stream in the background...

    # 3. Inspect pipeline health
    print(observra.get_stats())
    ```

For framework-specific setup, see the
[Getting Started guides](https://open-agent-ai-security.github.io/observra/guide/index.html).
"""

from __future__ import annotations

import logging
from typing import Optional

__version__ = "1.0.8"

logger = logging.getLogger(__name__)

_worker: Optional["BackgroundWorker"] = None  # noqa: F821
_queue: Optional["DropOldestQueue"] = None  # noqa: F821
_cost_calculator = None
_cost_threshold = None
_max_sequence_length: int = 100


class _QueueProxy:
    """Proxy that delegates to the current queue, surviving re-init.

    Adapters hold a reference to this proxy. When initialize() is called
    again, the proxy's target is swapped — existing adapters transparently
    start writing to the new queue.
    """

    def __init__(self):
        self._target = None

    def set_target(self, queue):
        self._target = queue

    def put_nowait(self, item):
        if self._target is not None:
            self._target.put_nowait(item)

    def get_stats(self):
        if self._target is not None:
            return self._target.get_stats()
        return {"enqueued": 0, "dropped": 0, "depth": 0}


_queue_proxy = _QueueProxy()


def initialize(backend: str = "jsonl", **kwargs) -> None:
    """Initialize the global telemetry pipeline with a named backend.

    Tears down any existing pipeline and replaces it with a new one. Adapters
    created with `create_plugin` keep working across re-initialization — they
    hold a proxy whose target is swapped to the new queue.

    Args:
        backend: Backend type name. One of ``"jsonl"`` (newline-delimited JSON,
            the default), ``"webhook"``, ``"otel"`` (OpenTelemetry spans),
            ``"otel_log"`` (OpenTelemetry logs), ``"multi"`` (fan out to several
            backends at once), or ``"exabeam"`` (Exabeam SIEM).
        **kwargs: Passed through to the backend constructor — e.g. ``path=`` for
            ``"jsonl"``. ``queue_size`` (default ``1000``) caps the in-memory
            event buffer.

    Raises:
        ValueError: If ``backend`` is not a recognized name.

    Example:
        ```python
        import observra

        # Local file (default backend)
        observra.initialize(backend="jsonl", path="telemetry.jsonl")
        ```

    Note:
        Call this once at application startup, before creating adapters. The
        pipeline runs on a background worker, so this never blocks your agent's
        hot path.
    """
    from observra.core.queue import DropOldestQueue
    from observra.core.worker import BackgroundWorker

    global _worker, _queue

    storage = _create_backend(backend, **kwargs)

    if _worker is not None:
        _worker._shutdown()

    event_queue = DropOldestQueue(maxsize=kwargs.pop("queue_size", 1000) if "queue_size" in kwargs else 1000)
    worker = BackgroundWorker(event_queue=event_queue, storage_backend=storage)

    _queue = event_queue
    _worker = worker
    _queue_proxy.set_target(event_queue)


def _create_backend(backend_type: str, **kwargs):
    """Factory for creating backend instances by name."""
    if backend_type == "jsonl":
        from observra.backends.jsonl import JSONLBackend

        kwargs.setdefault("path", "telemetry.jsonl")
        return JSONLBackend(**kwargs)
    elif backend_type == "webhook":
        from observra.backends.webhook import WebhookBackend

        return WebhookBackend(**kwargs)
    elif backend_type == "otel":
        from observra.backends.otel import OTelExportBackend

        return OTelExportBackend(**kwargs)
    elif backend_type == "otel_log":
        from observra.backends.otel_log import OTelLogBackend

        return OTelLogBackend(**kwargs)
    elif backend_type == "multi":
        from observra.backends.multi import MultiBackend

        return MultiBackend(**kwargs)
    elif backend_type == "exabeam":
        from observra.senders.exabeam import ExabeamSenderBackend

        return ExabeamSenderBackend(**kwargs)
    else:
        raise ValueError(f"Unknown backend type: {backend_type!r}")


def create_plugin(framework: str = "adk", **kwargs):
    """Create a framework adapter connected to the global pipeline.

    The adapter forwards your agent framework's callbacks into the pipeline
    started by `initialize`. Attach the returned object the way each framework
    expects — e.g. as an ADK plugin, or registered as a callback handler.

    Args:
        framework: One of ``"adk"``, ``"claude"``, ``"openai"``,
            ``"langchain"``, or ``"pydantic-ai"``.
        **kwargs: Passed to the adapter constructor (framework-specific).

    Returns:
        The framework-specific adapter instance.

    Raises:
        ValueError: If ``framework`` is not recognized.

    Example:
        ```python
        import observra
        observra.initialize(backend="jsonl")

        # Google ADK: pass the plugin when constructing your agent
        plugin = observra.create_plugin("adk")
        # agent = Agent(..., plugins=[plugin])
        ```

    Note:
        Requires the matching extra to be installed, e.g.
        ``pip install observra[adk]``.
    """
    queue = _queue_proxy

    if framework == "adk":
        from observra.adapters.adk import TelemetryPlugin

        return TelemetryPlugin(queue=queue, **kwargs)
    elif framework == "claude":
        from observra.adapters.claude import ClaudeAdapter

        return ClaudeAdapter(queue=queue, **kwargs)
    elif framework == "openai":
        from observra.adapters.openai import OpenAIAdapter

        return OpenAIAdapter(queue=queue, **kwargs)
    elif framework == "langchain":
        from observra.adapters.langchain import LangChainAdapter

        return LangChainAdapter(queue=queue, **kwargs)
    elif framework in ("pydantic-ai", "pydantic_ai"):
        from observra.adapters.pydantic_ai import PydanticAIAdapter

        return PydanticAIAdapter(queue=queue, **kwargs)
    else:
        raise ValueError(f"Unknown framework: {framework!r}. Supported: adk, claude, openai, langchain, pydantic-ai")


def create_logging_handler(level: int = logging.NOTSET):
    """Bridge Python's standard ``logging`` into the telemetry pipeline.

    Returns a `logging.Handler` that converts each log record into a telemetry
    event on the global pipeline. Attach it to any logger to capture application
    logs alongside agent events.

    Args:
        level: Minimum log level to capture (default: ``logging.NOTSET`` — the
            handler inherits the logger's effective level).

    Returns:
        A `logging.Handler` that emits telemetry events.

    Example:
        ```python
        import logging, observra
        observra.initialize(backend="jsonl")
        logging.getLogger().addHandler(observra.create_logging_handler())
        ```
    """
    from observra.core.logging_handler import TelemetryLoggingHandler

    return TelemetryLoggingHandler(queue=_queue_proxy, level=level)


def get_stats() -> dict:
    """Return live pipeline statistics.

    Returns:
        A dict of queue and worker counters — ``enqueued``, ``dropped``,
        ``current_size`` (current queue depth), ``events_processed`` and ``errors``.
        Returns an empty dict if `initialize` has not been called yet.

    Example:
        ```python
        stats = observra.get_stats()
        print(stats.get("dropped", 0), "events dropped")
        ```
    """
    if _worker is None:
        return {}

    stats = _queue.get_stats()
    stats.update(
        {
            "events_processed": _worker._events_processed,
            "errors": _worker._errors,
        }
    )
    return stats


from observra import observability  # noqa: E402
from observra.core.events import TelemetryEvent  # noqa: E402
from observra.core.storage import StorageBackend  # noqa: E402

get_metrics = observability.get_metrics

__all__ = [
    "__version__",
    "initialize",
    "create_plugin",
    "create_logging_handler",
    "get_stats",
    "get_metrics",
    "observability",
    "TelemetryEvent",
    "StorageBackend",
]
