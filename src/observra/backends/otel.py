# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""OTelExportBackend: exports TelemetryEvents as OTel spans via OTLP HTTP.

This backend implements the StorageBackend Protocol and creates a PRIVATE
internal TracerProvider with BatchSpanProcessor + OTLPSpanExporter. It is
completely isolated from any user-configured global TracerProvider (e.g.,
one that a PydanticAI adapter may have registered).

Requires: pip install observra[otel]
  - opentelemetry-sdk>=1.0.0
  - opentelemetry-exporter-otlp-proto-http>=1.0.0
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind

from observra.core.events import TelemetryEvent
from observra.core.types import BackendStats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GenAI semantic convention attribute key constants (string literals — avoids
# dependency on the beta opentelemetry-semantic-conventions package)
# ---------------------------------------------------------------------------

# Operation-level attributes
_GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
_GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
_GEN_AI_SYSTEM = "gen_ai.system"  # deprecated in semconv 1.36+ but required per phase spec

# Model-level attributes
_GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
_GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"

# Usage attributes
_GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
_GEN_AI_USAGE_CACHE_READ_TOKENS = "gen_ai.usage.details.cache_read_tokens"

# Tool attributes
_GEN_AI_TOOL_NAME = "gen_ai.tool.name"
_GEN_AI_TOOL_ARGUMENTS = "gen_ai.tool.call.arguments"

# Agent attributes
_GEN_AI_AGENT_NAME = "gen_ai.agent.name"

# Error attributes
_ERROR_TYPE = "error.type"

# Custom observra namespace attributes
_AT_EVENT_ID = "observra.event_id"
_AT_EVENT_TYPE = "observra.event_type"
_AT_TRACE_ID = "observra.trace_id"
_AT_SESSION_ID = "observra.session_id"
_AT_FRAMEWORK = "observra.framework"
_AT_COST_USD = "observra.cost_usd"
_AT_CIM_VERSION = "observra.cim_version"
_AT_HAS_INJECTION = "observra.has_injection_patterns"
_AT_INJECTION_PATTERNS = "observra.injection_patterns"


def _event_type_to_span_name(event: TelemetryEvent) -> str:
    """Map TelemetryEvent.event_type to an OTel span name.

    Follows GenAI semantic conventions for span naming:
    - chat {model} for model-related events
    - execute_tool {tool} for tool-related events
    - invoke_agent {agent} for agent/session events
    - passthrough event_type for all other types

    Args:
        event: TelemetryEvent to derive the span name from

    Returns:
        Span name string following GenAI naming conventions
    """
    et = event.event_type

    if et in ("model_response", "model_request"):
        model = event.model_name or "unknown"
        return f"chat {model}"

    elif et in ("tool_start", "tool_end", "tool_error"):
        # Try event.tool_name first, then event.data dict, fallback to 'unknown'
        tool = event.tool_name or (event.data or {}).get("tool_name") or "unknown"
        return f"execute_tool {tool}"

    elif et in ("session_start", "session_end", "agent_start", "agent_end", "agent_handoff"):
        agent = event.agent_name or "agent"
        return f"invoke_agent {agent}"

    else:
        # Passthrough for cost_threshold_exceeded, depth_exceeded, error, etc.
        return et


def _apply_gen_ai_attributes(span, event: TelemetryEvent) -> None:
    """Set GenAI semantic convention attributes on the span from a TelemetryEvent.

    Applies all applicable attributes from the GenAI semantic conventions,
    plus custom observra.* namespace attributes.

    Args:
        span: OTel Span (opentelemetry.trace.Span) to set attributes on
        event: TelemetryEvent to extract values from
    """
    et = event.event_type

    # Operation name: gen_ai.operation.name (required by GenAI semconv)
    if et in ("model_response", "model_request"):
        span.set_attribute(_GEN_AI_OPERATION_NAME, "chat")
    elif et in ("tool_start", "tool_end", "tool_error"):
        span.set_attribute(_GEN_AI_OPERATION_NAME, "execute_tool")
    elif et in ("session_start", "session_end", "agent_start", "agent_end", "agent_handoff"):
        span.set_attribute(_GEN_AI_OPERATION_NAME, "invoke_agent")
    # No operation.name for passthrough types (cost_threshold_exceeded, etc.)

    # Provider name: gen_ai.provider.name (current) + gen_ai.system (deprecated, backward compat)
    # Emit BOTH — gen_ai.system is deprecated but required per phase specification
    if event.framework and event.framework != "unknown":
        span.set_attribute(_GEN_AI_PROVIDER_NAME, event.framework)
        span.set_attribute(_GEN_AI_SYSTEM, event.framework)

    # Model name: gen_ai.request.model + gen_ai.response.model (skip if None)
    if event.model_name:
        span.set_attribute(_GEN_AI_REQUEST_MODEL, event.model_name)
        span.set_attribute(_GEN_AI_RESPONSE_MODEL, event.model_name)

    # Agent name: gen_ai.agent.name (skip if None)
    if event.agent_name:
        span.set_attribute(_GEN_AI_AGENT_NAME, event.agent_name)

    # Tool name: gen_ai.tool.name (skip if None)
    if event.tool_name:
        span.set_attribute(_GEN_AI_TOOL_NAME, event.tool_name)

    # Custom observra namespace attributes (always set — never None from event)
    span.set_attribute(_AT_EVENT_ID, event.event_id)
    span.set_attribute(_AT_EVENT_TYPE, et)
    span.set_attribute(_AT_TRACE_ID, event.trace_id)
    span.set_attribute(_AT_SESSION_ID, event.session_id)
    span.set_attribute(_AT_FRAMEWORK, event.framework or "unknown")
    span.set_attribute(_AT_CIM_VERSION, event.cim_version or "1.0")

    # Extract token/cost/tool data from event.data dict (skip any that are None)
    data = event.data or {}
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    cost_usd = data.get("cost_usd")
    tool_args = data.get("tool_args")
    error_type = data.get("error_type_name")
    cached_tokens = data.get("cached_tokens")

    if input_tokens is not None:
        span.set_attribute(_GEN_AI_USAGE_INPUT_TOKENS, int(input_tokens))
    if output_tokens is not None:
        span.set_attribute(_GEN_AI_USAGE_OUTPUT_TOKENS, int(output_tokens))
    if cost_usd is not None:
        span.set_attribute(_AT_COST_USD, float(cost_usd))
    if tool_args is not None:
        span.set_attribute(_GEN_AI_TOOL_ARGUMENTS, str(tool_args))
    if error_type is not None:
        span.set_attribute(_ERROR_TYPE, str(error_type))
    if cached_tokens is not None:
        span.set_attribute(_GEN_AI_USAGE_CACHE_READ_TOKENS, int(cached_tokens))

    has_injection = data.get("has_injection_patterns")
    injection_patterns = data.get("injection_patterns")
    if has_injection is not None:
        span.set_attribute(_AT_HAS_INJECTION, bool(has_injection))
    if injection_patterns:
        span.set_attribute(_AT_INJECTION_PATTERNS, ",".join(injection_patterns))


class OTelExportBackend:
    """StorageBackend that exports TelemetryEvents as OTel spans via OTLP HTTP.

    Implements StorageBackend Protocol. Creates a PRIVATE internal TracerProvider
    with BatchSpanProcessor + OTLPSpanExporter — completely isolated from the
    user's global TracerProvider (which adapters may use).

    NEVER calls trace.set_tracer_provider() — the private provider is accessed
    only via self._provider and self._tracer.

    Reads OTEL_EXPORTER_OTLP_ENDPOINT environment variable automatically when
    endpoint is not passed to the constructor (defaults to http://localhost:4318).
    BatchSpanProcessor tuning via OTEL_BSP_* environment variables.

    Caveats:
    - query() raises NotImplementedError (OTel is write-only from the SDK)
    - bytes_written is always 0 (not tracked for OTel spans)
    - close() blocks up to 5s for force_flush then calls shutdown()
      (shutdown may block up to 30s if OTLP endpoint is unreachable)

    Usage::

        # Via environment variable (recommended)
        # export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
        backend = OTelExportBackend()

        # Or explicit endpoint
        backend = OTelExportBackend(endpoint="http://localhost:4318/v1/traces")

        # With MultiBackend for local + remote export
        from observra.backends.multi import MultiBackend
        from observra.backends.jsonl import JSONLBackend
        multi = MultiBackend([JSONLBackend(path="telemetry.jsonl"), OTelExportBackend()])

    Requires::

        pip install observra[otel]
    """

    BACKEND_TYPE = "otel"

    def __init__(
        self,
        endpoint: Optional[str] = None,
        service_name: str = "observra",
        headers: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Initialize OTelExportBackend with a private TracerProvider.

        Args:
            endpoint: OTLP HTTP endpoint URL (e.g., "http://localhost:4318/v1/traces").
                None means read from OTEL_EXPORTER_OTLP_ENDPOINT env var,
                defaulting to http://localhost:4318.
            service_name: OTel service.name resource attribute (default: "observra").
            headers: Optional dict of HTTP headers for authentication (e.g., API keys).
            timeout: Optional request timeout in seconds.
        """
        resource = Resource.create({SERVICE_NAME: service_name})

        # Create PRIVATE TracerProvider — NEVER set as global provider
        self._provider = TracerProvider(resource=resource)

        # OTLPSpanExporter reads OTEL_EXPORTER_OTLP_ENDPOINT when endpoint=None
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=headers,
            timeout=timeout,
        )
        # BatchSpanProcessor: non-blocking, exports in background thread
        self._provider.add_span_processor(BatchSpanProcessor(exporter))

        # Get private tracer from OUR provider (not the global one)
        self._tracer = self._provider.get_tracer("observra", "2.0.0")

        # Stats tracking
        self._events_written: int = 0
        self._errors: int = 0
        self._oldest_ts: Optional[float] = None
        self._newest_ts: Optional[float] = None

        logger.debug(
            "OTelExportBackend initialized: endpoint=%s, service_name=%s",
            endpoint or "from OTEL_EXPORTER_OTLP_ENDPOINT env var",
            service_name,
        )

    def write(self, event: TelemetryEvent) -> None:
        """Export a TelemetryEvent as an OTel span.

        Creates a span with start_time derived from event.timestamp (nanoseconds),
        applies all GenAI semantic convention attributes, and ends the span
        (end_time defaults to now — acceptable for near-real-time telemetry).

        Errors are caught and logged — write() never raises.

        Args:
            event: TelemetryEvent to export as an OTel span
        """
        try:
            span_name = _event_type_to_span_name(event)
            # OTel SDK requires nanoseconds since Unix epoch for start_time
            start_time_ns = int(event.timestamp * 1_000_000_000)

            with self._tracer.start_as_current_span(
                span_name,
                kind=SpanKind.INTERNAL,
                start_time=start_time_ns,
            ) as span:
                _apply_gen_ai_attributes(span, event)
            # Span is ended when the context manager exits (end_time = now)

            self._events_written += 1
            ts = event.timestamp
            if self._oldest_ts is None or ts < self._oldest_ts:
                self._oldest_ts = ts
            if self._newest_ts is None or ts > self._newest_ts:
                self._newest_ts = ts

        except Exception as e:
            self._errors += 1
            logger.error("OTelExportBackend.write error: %s", e, exc_info=True)

    def flush(self) -> None:
        """Force-flush all buffered spans to the OTLP endpoint.

        Calls BatchSpanProcessor.force_flush() with a 5s timeout.
        Errors are caught and logged — flush() never raises.
        """
        try:
            self._provider.force_flush(timeout_millis=5000)
        except Exception as e:
            self._errors += 1
            logger.error("OTelExportBackend.flush error: %s", e, exc_info=True)

    def close(self) -> None:
        """Flush all pending spans and shut down the OTLP pipeline.

        Calls force_flush(5s) first to minimize data loss, then shutdown().
        Note: shutdown() may block up to 30s if the OTLP endpoint is unreachable.
        """
        try:
            self._provider.force_flush(timeout_millis=5000)
        except Exception:
            pass  # Swallow flush errors — we still want to proceed with shutdown
        try:
            self._provider.shutdown()
        except Exception as e:
            logger.error("OTelExportBackend.close/shutdown error: %s", e, exc_info=True)

    def get_stats(self) -> BackendStats:
        """Return backend statistics.

        bytes_written is always 0 (OTel spans have no byte count equivalent).

        Returns:
            BackendStats with event_count (spans exported), backend_type="otel",
            and oldest/newest timestamps from written events.
        """
        return BackendStats(
            bytes_written=0,
            event_count=self._events_written,
            backend_type=self.BACKEND_TYPE,
            oldest_event_ts=self._oldest_ts,
            newest_event_ts=self._newest_ts,
        )

    def query(
        self,
        *,
        event_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        from_ts: Optional[float] = None,
        to_ts: Optional[float] = None,
        limit: int = 1000,
    ) -> Iterator[TelemetryEvent]:
        """Not supported: OTel export is write-only.

        Raises:
            NotImplementedError: Always. Use JSONLBackend for querying,
                or wrap both in a MultiBackend.
        """
        raise NotImplementedError("OTelExportBackend does not support query(). Querying is not supported in v1.")
