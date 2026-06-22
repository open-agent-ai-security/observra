"""Observra — Framework-agnostic agent behavior analytics."""

from __future__ import annotations

import logging
from typing import Optional

__version__ = "1.0.1"

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

    Tears down any existing pipeline and replaces it with a new one.
    Existing adapters continue working via the queue proxy.

    Args:
        backend: Backend type name. Supported: "jsonl", "webhook", "otel",
                 "otel_log", "multi", "exabeam".
        **kwargs: Arguments passed to the backend constructor.

    Raises:
        ValueError: If backend type is not recognized.
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

        return JSONLBackend(path=kwargs.get("path", "telemetry.jsonl"))
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
    """Create a framework adapter plugin connected to the global pipeline.

    Args:
        framework: One of "adk", "claude", "openai", "langchain", "pydantic-ai".
        **kwargs: Additional arguments passed to the adapter constructor.

    Returns:
        The framework-specific adapter/plugin instance.

    Raises:
        ValueError: If framework is not recognized.
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
    """Create a TelemetryLoggingHandler bridging stdlib logging to telemetry.

    Args:
        level: Minimum log level to capture (default: NOTSET).

    Returns:
        A logging.Handler that converts log records to telemetry events.
    """
    from observra.core.logging_handler import TelemetryLoggingHandler

    return TelemetryLoggingHandler(queue=_queue_proxy, level=level)


def get_stats() -> dict:
    """Get pipeline statistics.

    Returns a dict with queue and worker stats. Returns empty dict
    if initialize() hasn't been called.
    """
    if _worker is None:
        return {}

    stats = _queue.get_stats()
    stats.update(
        {
            "events_processed": _worker.events_processed,
            "errors": _worker.errors,
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
