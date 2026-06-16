"""ExabeamSenderBackend — HTTPS webhook delivery to Exabeam SIEM."""

import logging
import os
from datetime import datetime, timezone
from typing import Iterator

import requests

from aba_telemetry.core.events import TelemetryEvent
from aba_telemetry.core.types import BackendStats

logger = logging.getLogger(__name__)

_CANONICAL_FIELDS: frozenset[str] = frozenset({
    "time", "event_id", "event_type", "framework",
    "session_id", "trace_id", "span_id",
    "agent_name", "tool_name", "model_name",
    "mcp_agent_id", "mcp_session_id",
    "injection_detected", "has_injection_patterns", "injection_patterns",
    "tool_velocity", "tool_sequence", "suspicious_sequence",
    "delegation_depth", "error_type_name", "is_retryable",
})


class ExabeamSenderBackend:
    """StorageBackend implementation that POSTs events to Exabeam via HTTPS.

    Reads EXABEAM_ENDPOINT and EXABEAM_API_KEY from environment variables at
    instantiation. Raises ValueError at startup if TLS not enforced or vars missing.

    Failure isolation: write() never re-raises — webhook failures are logged
    and the BackgroundWorker daemon thread continues unaffected (FR25, NFR-R1).

    No imports from aba_telemetry.mcp — [mcp] and [exabeam] extras are
    fully independent.
    """

    BACKEND_TYPE = "exabeam"

    def __init__(self) -> None:
        endpoint = os.environ.get("EXABEAM_ENDPOINT")
        if not endpoint:
            raise ValueError("EXABEAM_ENDPOINT environment variable not set")
        if not endpoint.startswith("https://"):
            raise ValueError(
                "EXABEAM_ENDPOINT must use HTTPS. Got: %s" % endpoint
            )
        api_key = os.environ.get("EXABEAM_API_KEY")
        if not api_key:
            raise ValueError("EXABEAM_API_KEY environment variable not set")

        mode = os.environ.get("EXABEAM_PAYLOAD_MODE", "json")
        if mode not in {"json", "raw"}:
            raise ValueError(
                "EXABEAM_PAYLOAD_MODE must be 'json' or 'raw'. Got: %s" % mode
            )

        field_map: dict = {}
        for env_key, env_val in os.environ.items():
            if not env_key.startswith("EXABEAM_FIELD_"):
                continue
            canonical = env_key[len("EXABEAM_FIELD_"):].lower()
            if canonical not in _CANONICAL_FIELDS:
                logger.warning(
                    "EXABEAM_FIELD_%s is not a known canonical field — override ignored",
                    canonical.upper(),
                )
                continue
            field_map[canonical] = env_val
        self._field_map = field_map

        self._endpoint = endpoint
        self._api_key = api_key
        self._payload_mode = mode
        self._write_count = 0

    def __repr__(self) -> str:
        base = (
            "ExabeamSenderBackend(endpoint=%s, api_key=<redacted>, payload_mode=%s"
            % (self._endpoint, self._payload_mode)
        )
        if self._field_map:
            base += ", field_overrides=%d" % len(self._field_map)
        return base + ")"

    def _f(self, canonical: str) -> str:
        """Resolve canonical field name to override name (or itself if no override)."""
        return self._field_map.get(canonical, canonical)

    def build_payload(self, event: TelemetryEvent) -> dict:
        """Build structured JSON payload for Exabeam webhook collector."""
        data = event.data or {}
        return {
            self._f("time"): datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat(),
            self._f("event_id"): event.event_id,
            self._f("event_type"): event.event_type,
            self._f("framework"): event.framework,
            self._f("session_id"): event.session_id,
            self._f("trace_id"): event.trace_id,
            self._f("span_id"): event.span_id,
            self._f("agent_name"): event.agent_name,
            self._f("tool_name"): event.tool_name or None,
            self._f("model_name"): event.model_name,
            self._f("mcp_agent_id"): data.get("mcp_agent_id"),
            self._f("mcp_session_id"): data.get("mcp_session_id"),
            self._f("injection_detected"): bool(data.get("injection_patterns")),
            self._f("has_injection_patterns"): data.get("has_injection_patterns"),
            self._f("injection_patterns"): data.get("injection_patterns"),
            self._f("tool_velocity"): data.get("tool_velocity"),
            self._f("tool_sequence"): data.get("tool_sequence"),
            self._f("suspicious_sequence"): data.get("suspicious_sequence"),
            self._f("delegation_depth"): data.get("delegation_depth"),
            self._f("error_type_name"): data.get("error_type_name"),
            self._f("is_retryable"): data.get("is_retryable"),
            # tool_inputs and tool_outputs intentionally NOT included
        }

    def build_raw_payload(self, event: TelemetryEvent) -> dict:
        """Build raw serialized TelemetryEvent as flat JSON blob.

        ALL fields included — including tool_inputs and tool_outputs
        that are excluded from structured mode (AC#4).
        event.data fields are inlined at top level (no nested 'data' key).
        injection_detected always promoted as top-level boolean (FR24/NFR-S5).
        """
        data = event.data or {}
        payload = {
            "time": datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat(),
            "event_id": event.event_id,
            "event_type": event.event_type,
            "framework": event.framework,
            "session_id": event.session_id,
            "trace_id": event.trace_id,
            "span_id": event.span_id,
            "agent_name": event.agent_name,
            "model_name": event.model_name,
            # Inline ALL data fields (flat — no nested "data" key)
            **data,
            # These always win over any same-named keys inside **data
            "tool_name": event.tool_name or None,
            "skill_name": event.skill_name,
            # injection_detected always top-level boolean (FR24/NFR-S5)
            "injection_detected": bool(data.get("injection_patterns")),
        }
        return payload

    def write(self, event: TelemetryEvent) -> None:
        """POST event to Exabeam webhook endpoint. Failure is isolated — never re-raises."""
        try:
            payload = self.build_raw_payload(event) if self._payload_mode == "raw" else self.build_payload(event)
            resp = requests.post(
                self._endpoint,
                json=payload,
                headers={"Authorization": "Bearer %s" % self._api_key},
                timeout=5.0,
                verify=True,
            )
            resp.raise_for_status()
            self._write_count += 1
        except Exception as e:
            logger.warning(
                "Exabeam webhook delivery failed for event %s: %s: %s",
                event.event_id,
                type(e).__name__,
                e,
            )

    def flush(self) -> None:
        """No-op — HTTP delivery is fire-and-forget with no internal buffer."""

    def close(self) -> None:
        """Flush and release resources (no-op for HTTP sender)."""
        self.flush()

    def get_stats(self) -> BackendStats:
        return BackendStats(
            bytes_written=0,
            event_count=self._write_count,
            backend_type=self.BACKEND_TYPE,
            oldest_event_ts=None,
            newest_event_ts=None,
        )

    def query(self, **kwargs) -> Iterator[TelemetryEvent]:
        raise NotImplementedError(
            "ExabeamSenderBackend does not support query(). "
            "Querying is not supported in v1."
        )
