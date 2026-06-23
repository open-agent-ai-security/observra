# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""OTelLogBackend: exports TelemetryEvents as OTel log records via OTLP HTTP.

This backend implements the StorageBackend Protocol and creates a PRIVATE
internal LoggerProvider with BatchLogRecordProcessor + OTLPLogExporter. It is
completely isolated from any user-configured global LoggerProvider.

Requires: pip install observra[otel]
  - opentelemetry-sdk>=1.0.0
  - opentelemetry-exporter-otlp-proto-http>=1.0.0
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterator, Literal, Optional

from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from observra.core.events import TelemetryEvent
from observra.core.types import BackendStats

logger = logging.getLogger(__name__)

# Severity mapping: event_type → OTel SeverityNumber
_SEVERITY_MAP: dict[str, SeverityNumber] = {
    "session_start": SeverityNumber.INFO,
    "session_end": SeverityNumber.INFO,
    "agent_start": SeverityNumber.INFO,
    "agent_end": SeverityNumber.INFO,
    "model_request": SeverityNumber.INFO,
    "model_response": SeverityNumber.INFO,
    "tool_start": SeverityNumber.INFO,
    "tool_end": SeverityNumber.INFO,
    "stream_event": SeverityNumber.DEBUG,
    "adapter_close": SeverityNumber.INFO,
    "user_message": SeverityNumber.INFO,
    "model_error": SeverityNumber.ERROR,
    "tool_error": SeverityNumber.ERROR,
    "turn_duration": SeverityNumber.INFO,
    "cost_threshold_exceeded": SeverityNumber.WARN,
    "depth_exceeded": SeverityNumber.WARN,
    "agent_handoff": SeverityNumber.INFO,
    "agent_handoff_error": SeverityNumber.ERROR,
}

# Attribute keys (mirrors otel.py span backend for consistency)
_AT_EVENT_ID = "observra.event_id"
_AT_EVENT_TYPE = "observra.event_type"
_AT_TRACE_ID = "observra.trace_id"
_AT_SESSION_ID = "observra.session_id"
_AT_FRAMEWORK = "observra.framework"
_AT_COST_USD = "observra.cost_usd"
_AT_SCHEMA = "observra.schema"
_AT_CIM_VERSION = "observra.cim_version"
_AT_HAS_INJECTION = "observra.has_injection_patterns"
_AT_INJECTION_PATTERNS = "observra.injection_patterns"

_GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
_GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
_GEN_AI_AGENT_NAME = "gen_ai.agent.name"
_GEN_AI_TOOL_NAME = "gen_ai.tool.name"
_GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
_GEN_AI_TOOL_ARGUMENTS = "gen_ai.tool.call.arguments"
_GEN_AI_USAGE_CACHE_READ_TOKENS = "gen_ai.usage.details.cache_read_tokens"
_ERROR_TYPE = "error.type"


def _build_safe_body(event: TelemetryEvent) -> dict:
    """Build a JSON-safe body dict containing only non-PII fields.

    Exports the same fields promoted to OTel attributes — excludes prompt text,
    response text, tool results, and other payload content that may contain
    sensitive data.
    """
    data = event.data or {}
    body: dict = {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "trace_id": event.trace_id,
        "session_id": event.session_id,
        "span_id": event.span_id,
        "event_type": event.event_type,
        "framework": event.framework or "unknown",
        "cim_version": event.cim_version,
    }

    if event.agent_name:
        body["agent_name"] = event.agent_name
    if event.model_name:
        body["model_name"] = event.model_name
    if event.tool_name:
        body["tool_name"] = event.tool_name

    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    cached_tokens = data.get("cached_tokens")
    cost_usd = data.get("cost_usd")
    error_type = data.get("error_type_name")
    error_message = data.get("error_message")
    duration_ms = data.get("duration_ms")
    stop_reason = data.get("stop_reason")
    source_agent = data.get("source_agent")
    target_agent = data.get("target_agent")

    if input_tokens is not None:
        body["input_tokens"] = int(input_tokens)
    if output_tokens is not None:
        body["output_tokens"] = int(output_tokens)
    if cached_tokens is not None:
        body["cached_tokens"] = int(cached_tokens)
    if cost_usd is not None:
        body["cost_usd"] = float(cost_usd)
    if error_type is not None:
        body["error_type"] = str(error_type)
    if error_message is not None:
        body["error_message"] = str(error_message)
    if duration_ms is not None:
        body["duration_ms"] = duration_ms
    if stop_reason is not None:
        body["stop_reason"] = str(stop_reason)
    if source_agent is not None:
        body["source_agent"] = str(source_agent)
    if target_agent is not None:
        body["target_agent"] = str(target_agent)

    has_injection = data.get("has_injection_patterns")
    injection_patterns = data.get("injection_patterns")
    if has_injection is not None:
        body["has_injection_patterns"] = bool(has_injection)
    if injection_patterns:
        body["injection_patterns"] = list(injection_patterns)

    return body


_EVENT_TYPE_TO_SENSOR: dict[str, str] = {
    "user_message": "user",
    "tool_start": "tool_start",
    "tool_end": "tool_end",
    "tool_error": "tool_error",
    "session_start": "session_start",
    "session_end": "session_end",
    "agent_start": "agent_start",
    "agent_end": "agent_end",
    "agent_handoff": "agent_handoff",
    "agent_handoff_error": "agent_handoff_error",
    "model_error": "model_error",
    "turn_duration": "turn_duration",
    "cost_threshold_exceeded": "cost_threshold_exceeded",
    "depth_exceeded": "depth_exceeded",
    "stream_event": "stream_event",
    "adapter_close": "adapter_close",
}

_TOKEN_MAP: dict[str, str] = {
    "input_tokens": "in",
    "output_tokens": "out",
    "cached_tokens": "cache_read",
    "cache_read_tokens": "cache_read",
    "cache_creation_tokens": "cache_creation",
}


def _build_sensor_body(event: TelemetryEvent) -> dict:
    """Build a sensor-compatible body dict (short keys, composite event types).

    Matches the format produced by the CLI JSONL writer / aba-sensor forwarder,
    enabling existing SIEM parsers to consume OTel log bodies without modification.
    """
    data = event.data or {}
    ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()

    rec: dict = {
        "ts": ts,
        "session": event.session_id[:8] if event.session_id else None,
        "type": _EVENT_TYPE_TO_SENSOR.get(event.event_type, event.event_type),
        "framework": event.framework or "unknown",
        "schema": "observra",
        "cim_version": event.cim_version,
    }

    if event.agent_name:
        rec["agent"] = event.agent_name
    if event.model_name:
        rec["model"] = event.model_name
    if event.tool_name:
        rec["tool"] = event.tool_name

    for key, short in _TOKEN_MAP.items():
        val = data.get(key)
        if val is not None:
            rec[short] = int(val)

    cost_usd = data.get("cost_usd")
    if cost_usd is not None:
        rec["cost_usd"] = float(cost_usd)

    stop_reason = data.get("stop_reason")
    if stop_reason is not None:
        rec["stop"] = str(stop_reason)

    duration_ms = data.get("duration_ms")
    if duration_ms is not None:
        rec["duration_ms"] = duration_ms

    error_type = data.get("error_type_name")
    error_message = data.get("error_message")
    if error_type or error_message:
        rec["error"] = str(error_message or error_type)

    source_agent = data.get("source_agent")
    target_agent = data.get("target_agent")
    if source_agent is not None:
        rec["source_agent"] = str(source_agent)
    if target_agent is not None:
        rec["target_agent"] = str(target_agent)

    has_injection = data.get("has_injection_patterns")
    injection_patterns = data.get("injection_patterns")
    if has_injection is not None:
        rec["injection"] = bool(has_injection)
    if injection_patterns:
        rec["injection_patterns"] = list(injection_patterns)

    return rec


BodySchema = Literal["native", "sensor"]


def _build_attributes(event: TelemetryEvent) -> dict:
    """Build OTel log record attributes from a TelemetryEvent."""
    attrs: dict = {
        _AT_EVENT_ID: event.event_id,
        _AT_EVENT_TYPE: event.event_type,
        _AT_TRACE_ID: event.trace_id,
        _AT_SESSION_ID: event.session_id,
        _AT_FRAMEWORK: event.framework or "unknown",
        _AT_SCHEMA: "observra",
        _AT_CIM_VERSION: event.cim_version or "1.0",
    }

    if event.agent_name:
        attrs[_GEN_AI_AGENT_NAME] = event.agent_name
    if event.model_name:
        attrs[_GEN_AI_REQUEST_MODEL] = event.model_name
    if event.tool_name:
        attrs[_GEN_AI_TOOL_NAME] = event.tool_name

    et = event.event_type
    if et in ("model_response", "model_request"):
        attrs[_GEN_AI_OPERATION_NAME] = "chat"
    elif et in ("tool_start", "tool_end", "tool_error"):
        attrs[_GEN_AI_OPERATION_NAME] = "execute_tool"
    elif et in ("session_start", "session_end", "agent_start", "agent_end"):
        attrs[_GEN_AI_OPERATION_NAME] = "invoke_agent"

    data = event.data or {}
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    cached_tokens = data.get("cached_tokens")
    cost_usd = data.get("cost_usd")
    tool_args = data.get("tool_args")
    error_type = data.get("error_type_name")

    if input_tokens is not None:
        attrs[_GEN_AI_USAGE_INPUT_TOKENS] = int(input_tokens)
    if output_tokens is not None:
        attrs[_GEN_AI_USAGE_OUTPUT_TOKENS] = int(output_tokens)
    if cached_tokens is not None:
        attrs[_GEN_AI_USAGE_CACHE_READ_TOKENS] = int(cached_tokens)
    if cost_usd is not None:
        attrs[_AT_COST_USD] = float(cost_usd)
    if tool_args is not None:
        attrs[_GEN_AI_TOOL_ARGUMENTS] = str(tool_args)
    if error_type is not None:
        attrs[_ERROR_TYPE] = str(error_type)

    has_injection = data.get("has_injection_patterns")
    injection_patterns = data.get("injection_patterns")
    if has_injection is not None:
        attrs[_AT_HAS_INJECTION] = bool(has_injection)
    if injection_patterns:
        attrs[_AT_INJECTION_PATTERNS] = ",".join(injection_patterns)

    return attrs


class OTelLogBackend:
    """StorageBackend that exports TelemetryEvents as OTel log records via OTLP HTTP.

    Implements StorageBackend Protocol. Creates a PRIVATE internal LoggerProvider
    with BatchLogRecordProcessor + OTLPLogExporter — completely isolated from
    any global LoggerProvider.

    Usage::

        backend = OTelLogBackend(
            endpoint="https://your-dt.live.dynatrace.com/api/v2/otlp/v1/logs",
            headers={"Authorization": "Api-Token dt0c01.xxx"},
            service_name="my-agent-service",
        )

    Requires::

        pip install observra[otel]
    """

    BACKEND_TYPE = "otel_log"

    def __init__(
        self,
        endpoint: Optional[str] = None,
        service_name: str = "observra",
        headers: Optional[dict] = None,
        timeout: Optional[int] = None,
        body_schema: BodySchema = "native",
    ) -> None:
        """Initialize OTelLogBackend with a private LoggerProvider.

        Args:
            endpoint: OTLP HTTP endpoint URL for logs
                (e.g., "https://host/api/v2/otlp/v1/logs").
                None means read from OTEL_EXPORTER_OTLP_LOGS_ENDPOINT env var.
            service_name: OTel service.name resource attribute.
            headers: Optional dict of HTTP headers for authentication.
            timeout: Optional request timeout in seconds.
            body_schema: Body format — "native" (default) uses library field names,
                "sensor" uses short keys matching aba-sensor/CLI output for
                parser compatibility.
        """
        if body_schema not in ("native", "sensor"):
            raise ValueError(f"Invalid body_schema: {body_schema}. Expected 'native' or 'sensor'.")
        self._body_schema: BodySchema = body_schema
        resource = Resource.create({SERVICE_NAME: service_name})

        self._provider = LoggerProvider(resource=resource)

        exporter = OTLPLogExporter(
            endpoint=endpoint,
            headers=headers,
            timeout=timeout,
        )
        self._provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

        self._logger = self._provider.get_logger("observra", "2.0.0")

        self._events_written: int = 0
        self._errors: int = 0
        self._oldest_ts: Optional[float] = None
        self._newest_ts: Optional[float] = None

        logger.debug(
            "OTelLogBackend initialized: endpoint=%s, service_name=%s, body_schema=%s",
            endpoint or "from OTEL_EXPORTER_OTLP_LOGS_ENDPOINT env var",
            service_name,
            body_schema,
        )

    def write(self, event: TelemetryEvent) -> None:
        """Export a TelemetryEvent as an OTel log record.

        Args:
            event: TelemetryEvent to export as a log record
        """
        try:
            severity = _SEVERITY_MAP.get(event.event_type, SeverityNumber.INFO)
            attributes = _build_attributes(event)
            timestamp_ns = int(event.timestamp * 1_000_000_000)

            if self._body_schema == "sensor":
                body_dict = _build_sensor_body(event)
            else:
                body_dict = _build_safe_body(event)
            body = json.dumps(body_dict, separators=(",", ":"), default=str)

            log_record = LogRecord(
                timestamp=timestamp_ns,
                severity_number=severity,
                severity_text=severity.name,
                body=body,
                attributes=attributes,
            )
            self._logger.emit(log_record)

            self._events_written += 1
            ts = event.timestamp
            if self._oldest_ts is None or ts < self._oldest_ts:
                self._oldest_ts = ts
            if self._newest_ts is None or ts > self._newest_ts:
                self._newest_ts = ts

        except Exception as e:
            self._errors += 1
            logger.error("OTelLogBackend.write error: %s", e, exc_info=True)

    def flush(self) -> None:
        """Force-flush all buffered log records to the OTLP endpoint."""
        try:
            self._provider.force_flush(timeout_millis=5000)
        except Exception as e:
            self._errors += 1
            logger.error("OTelLogBackend.flush error: %s", e, exc_info=True)

    def close(self) -> None:
        """Flush pending records and shut down the OTLP pipeline."""
        try:
            self._provider.force_flush(timeout_millis=5000)
        except Exception:
            pass
        try:
            self._provider.shutdown()
        except Exception as e:
            logger.error("OTelLogBackend.close/shutdown error: %s", e, exc_info=True)

    def get_stats(self) -> BackendStats:
        """Return backend statistics."""
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
        """Not supported: OTel log export is write-only."""
        raise NotImplementedError("OTelLogBackend does not support query(). Querying is not supported in v1.")
