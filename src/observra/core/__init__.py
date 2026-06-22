# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Framework-agnostic core for agent telemetry."""

from .adapter import FrameworkAdapter
from .context import (
    add_to_session_cost,
    create_scoped_context,
    get_session_cost,
    get_session_id,
    get_span_id,
    get_trace_id,
    initialize_session,
    initialize_trace,
    new_span,
    reset_session_cost,
)
from .cost import CostCalculator, ModelPricing
from .events import FrameworkName, TelemetryEvent, configure_redactor, create_event
from .logging_handler import TelemetryLoggingHandler
from .queue import DropOldestQueue
from .redaction import Redactor
from .storage import StorageBackend, create_backend
from .types import BackendStats
from .worker import BackgroundWorker

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
