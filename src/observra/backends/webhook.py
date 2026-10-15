# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Generic webhook backend — POST telemetry events as JSON to any URL."""

import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Literal

from observra.core.events import TelemetryEvent
from observra.core.sensor_record import to_sensor_record
from observra.core.types import BackendStats

logger = logging.getLogger(__name__)


class WebhookBackend:
    """Lightweight webhook backend that POSTs events as JSON to any HTTP(S) URL.

    Intended for development, testing, and simple integrations where a full
    OTel pipeline is unnecessary. Uses stdlib urllib — no extra dependencies.

    Thread-safe: all shared state is protected by a lock. Network I/O is
    performed outside the lock to avoid blocking concurrent writers.

    Args:
        url: Destination URL (http or https).
        headers: Optional dict of extra headers (e.g. {"Authorization": "Bearer ..."}).
        timeout: HTTP request timeout in seconds (default: 5.0).
        batch_size: Number of events to buffer before sending (default: 1, send immediately).
        record_format: "sensor" (default) posts the agent-sensor record shape so
            one SIEM parser reads both; "native" posts the TelemetryEvent fields.
    """

    BACKEND_TYPE = "webhook"

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
        batch_size: int = 1,
        record_format: Literal["sensor", "native"] = "sensor",
    ):
        if record_format not in ("sensor", "native"):
            raise ValueError(f"Invalid record_format: {record_format}. Expected 'sensor' or 'native'.")
        self._record_format = record_format
        if not url:
            raise ValueError("WebhookBackend requires a non-empty url")
        if not url.startswith(("http://", "https://")):
            raise ValueError("WebhookBackend url must start with 'http://' or 'https://'")
        self._url = url
        self._headers = dict(headers) if headers else {}
        if timeout <= 0:
            raise ValueError("WebhookBackend timeout must be positive")
        self._timeout = timeout
        self._batch_size = max(1, batch_size)
        self._buffer: list[tuple[float, dict]] = []
        self._lock = threading.Lock()
        self._stats = {
            "events_sent": 0,
            "events_failed": 0,
            "bytes_sent": 0,
        }
        self._oldest_ts: float | None = None
        self._newest_ts: float | None = None

        logger.debug("Initialized WebhookBackend: url=%s, batch_size=%d", url, self._batch_size)

    def write(self, event: TelemetryEvent) -> None:
        """Buffer an event and flush when batch_size is reached."""
        data = to_sensor_record(event) if self._record_format == "sensor" else asdict(event)
        to_flush: list[tuple[float, dict]] | None = None

        with self._lock:
            self._buffer.append((event.timestamp, data))

            if len(self._buffer) >= self._batch_size:
                to_flush = list(self._buffer)
                self._buffer.clear()

        if to_flush:
            self._send_batch(to_flush)

    def _send_batch(self, batch: list[tuple[float, dict]]) -> None:
        """POST a batch of (timestamp, record) pairs to the webhook URL (no lock held)."""
        try:
            records = [rec for _, rec in batch]
            payload = records if (self._batch_size > 1 or len(records) > 1) else records[0]
            body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")

            req_headers = {"Content-Type": "application/json"}
            for k, v in self._headers.items():
                if k.lower() == "content-type":
                    req_headers.pop("Content-Type", None)
                req_headers[k] = v

            req = urllib.request.Request(
                self._url,
                data=body,
                headers=req_headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self._timeout):
                pass

            timestamps = [ts for ts, _ in batch]
            batch_oldest = min(timestamps) if timestamps else None
            batch_newest = max(timestamps) if timestamps else None

            with self._lock:
                self._stats["events_sent"] += len(batch)
                self._stats["bytes_sent"] += len(body)
                if batch_oldest is not None:
                    if self._oldest_ts is None or batch_oldest < self._oldest_ts:
                        self._oldest_ts = batch_oldest
                if batch_newest is not None:
                    if self._newest_ts is None or batch_newest > self._newest_ts:
                        self._newest_ts = batch_newest
        except urllib.error.HTTPError as e:
            try:
                with e:
                    err_bytes = e.read(1024)
                    err_body = err_bytes.decode("utf-8", errors="replace")
                    if len(err_bytes) == 1024:
                        err_body += "..."
            except Exception:
                err_body = ""
            logger.warning(
                "WebhookBackend POST failed with HTTP %d (%s): %s. Response: %s",
                e.code,
                self._url,
                e.reason,
                err_body,
            )
            with self._lock:
                self._stats["events_failed"] += len(batch)
        except Exception as e:
            logger.warning("WebhookBackend POST failed (%s): %s", self._url, e)
            with self._lock:
                self._stats["events_failed"] += len(batch)

    def flush(self) -> None:
        """Flush any remaining buffered events."""
        to_flush: list[dict] | None = None
        with self._lock:
            if self._buffer:
                to_flush = list(self._buffer)
                self._buffer.clear()
        if to_flush:
            self._send_batch(to_flush)

    def close(self) -> None:
        """Flush remaining events before shutdown."""
        self.flush()

    def get_stats(self) -> BackendStats:
        with self._lock:
            return BackendStats(
                bytes_written=self._stats["bytes_sent"],
                event_count=self._stats["events_sent"],
                backend_type="webhook",
                oldest_event_ts=self._oldest_ts,
                newest_event_ts=self._newest_ts,
            )
