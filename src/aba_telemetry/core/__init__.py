"""Framework-agnostic core for agent telemetry."""

from .events import TelemetryEvent, FrameworkName, create_event, configure_redactor
from .adapter import FrameworkAdapter
from .context import (
    initialize_session,
    initialize_trace,
    get_trace_id,
    get_session_id,
    get_span_id,
    get_session_cost,
    add_to_session_cost,
    reset_session_cost,
    new_span,
    create_scoped_context,
)
from .storage import StorageBackend, create_backend
from .queue import DropOldestQueue
from .worker import BackgroundWorker
from .cost import CostCalculator, ModelPricing
from .types import BackendStats
from .redaction import Redactor
from .logging_handler import TelemetryLoggingHandler

__all__ = [
    # Events
    "TelemetryEvent",
    "FrameworkName",
    "create_event",
    "configure_redactor",
    # Adapter Protocol
    "FrameworkAdapter",
    # Context
    "initialize_session",
    "initialize_trace",
    "get_trace_id",
    "get_session_id",
    "get_span_id",
    "get_session_cost",
    "add_to_session_cost",
    "reset_session_cost",
    "new_span",
    "create_scoped_context",
    # Storage
    "StorageBackend",
    "create_backend",
    # Queue
    "DropOldestQueue",
    # Worker
    "BackgroundWorker",
    # Cost
    "CostCalculator",
    "ModelPricing",
    # Types
    "BackendStats",
    # Redaction
    "Redactor",
    # Logging
    "TelemetryLoggingHandler",
]
