# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""forwarder_started / forwarder_stopped self-audit records.

Mirrors agent-sensor's ``src/audit.rs`` so the SIEM sees the same lifecycle
records from both. ``destinations`` lists where events are going (file path,
URL), so a pipeline repointed somewhere new is visible. A ``forwarder_started``
with no ``forwarder_stopped`` before the next one means the process was killed.
"""

import os
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from .events import TelemetryEvent, create_event
from .host_context import get_host_context

# Same session label agent-sensor uses for its own records.
_SESSION_LABEL = "fwd-self"
_FRAMEWORK_LABEL = "observra"


def _lifecycle_event(event_type: str, **data: Any) -> TelemetryEvent:
    event = create_event(
        event_type,
        agent_name=_FRAMEWORK_LABEL,
        framework=_FRAMEWORK_LABEL,
        version=get_host_context().library_version,
        pid=os.getpid(),
        **data,
    )
    return replace(event, session_id=_SESSION_LABEL)


def _destination(backend: Any) -> str:
    name = getattr(backend, "BACKEND_TYPE", type(backend).__name__)
    target = next((str(v) for a in ("_path", "_url", "_endpoint") if (v := getattr(backend, a, None))), None)
    if target and "://" in target:
        # Drop credentials and query string: either may carry a token.
        parts = urlsplit(target)
        host = f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname
        target = f"{parts.scheme}://{host}{parts.path}"
    return f"{name}:{target}" if target else name


def destinations(storage: Any) -> list[str]:
    """Return where ``storage`` sends events, one entry per backend."""
    return [_destination(b) for b in getattr(storage, "_backends", None) or [storage]]


def started_event(storage: Any) -> TelemetryEvent:
    return _lifecycle_event("forwarder_started", destinations=destinations(storage))


def stopped_event(uptime_secs: float) -> TelemetryEvent:
    return _lifecycle_event("forwarder_stopped", uptime_secs=int(uptime_secs))
