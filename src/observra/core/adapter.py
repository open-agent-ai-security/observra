# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Framework adapter protocol for agent telemetry."""
from typing import Protocol, runtime_checkable

from .events import TelemetryEvent


@runtime_checkable
class FrameworkAdapter(Protocol):
    """Protocol defining the framework adapter interface.

    Framework adapters capture events from their specific framework
    and emit TelemetryEvent instances. Adapters implement whichever
    methods (sync or async) their framework uses.

    Queue management and cost calculation are standalone core modules
    that adapters import directly as needed.
    """

    @property
    def framework_name(self) -> str:
        """Return the framework identifier (e.g., 'adk', 'claude')."""
        ...

    def emit(self, event: TelemetryEvent) -> None:
        """Route event to configured destination (queue or storage)."""
        ...
