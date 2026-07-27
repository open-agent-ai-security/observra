# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""SQLite storage backend for persistent local telemetry."""

import json
import logging
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Optional

from observra.core.events import TelemetryEvent
from observra.core.types import BackendStats

logger = logging.getLogger(__name__)

_PRUNE_CHECK_INTERVAL = 100


class SQLiteBackend:
    """SQLite storage backend with WAL mode and optional row pruning.

    Stores telemetry events in a local SQLite database for querying and
    replay. WAL mode enables concurrent reads while the background worker
    writes.

    Args:
        path: Database file path (default: "telemetry.db")
        table_name: Table to write events into (default: "events")
        max_rows: Optional row cap. Oldest events are pruned when exceeded.
    """

    def __init__(
        self,
        path: str | Path = "telemetry.db",
        table_name: str = "events",
        max_rows: Optional[int] = None,
    ):
        self._path = Path(path)
        self._table = table_name
        self._max_rows = max_rows
        self._event_count: int = 0
        self._bytes_written: int = 0
        self._oldest_ts: Optional[float] = None
        self._newest_ts: Optional[float] = None
        self._writes_since_prune: int = 0

        self._path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self._path.exists()

        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)

        if is_new:
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass

        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

        logger.debug(f"SQLiteBackend initialized: path={self._path}, max_rows={max_rows}")

    def _create_schema(self) -> None:
        t = self._table
        self._conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS {t} (
                event_id        TEXT PRIMARY KEY,
                timestamp       REAL NOT NULL,
                session_id      TEXT NOT NULL,
                trace_id        TEXT,
                span_id         TEXT,
                event_type      TEXT NOT NULL,
                agent_name      TEXT,
                tool_name       TEXT,
                model_name      TEXT,
                framework       TEXT,
                host            TEXT,
                data            TEXT,
                library_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_{t}_session_id ON {t}(session_id);
            CREATE INDEX IF NOT EXISTS idx_{t}_event_type ON {t}(event_type);
            CREATE INDEX IF NOT EXISTS idx_{t}_timestamp ON {t}(timestamp);
        """)
        self._conn.commit()

    def write(self, event: TelemetryEvent) -> None:
        data_json = json.dumps(event.data) if event.data else None
        row = (
            event.event_id,
            event.timestamp,
            event.session_id,
            event.trace_id,
            event.span_id,
            event.event_type,
            event.agent_name,
            event.tool_name,
            event.model_name,
            event.framework,
            event.host,
            data_json,
            event.library_version,
        )
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self._table} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
        self._event_count += 1
        self._bytes_written += len(data_json) if data_json else 0

        if self._oldest_ts is None or event.timestamp < self._oldest_ts:
            self._oldest_ts = event.timestamp
        if self._newest_ts is None or event.timestamp > self._newest_ts:
            self._newest_ts = event.timestamp

        self._writes_since_prune += 1
        if self._max_rows and self._writes_since_prune >= _PRUNE_CHECK_INTERVAL:
            self._prune()
            self._writes_since_prune = 0

    def _prune(self) -> None:
        cursor = self._conn.execute(f"SELECT COUNT(*) FROM {self._table}")
        count = cursor.fetchone()[0]
        if count > self._max_rows:
            excess = count - self._max_rows
            self._conn.execute(
                f"DELETE FROM {self._table} WHERE rowid IN "
                f"(SELECT rowid FROM {self._table} ORDER BY timestamp ASC LIMIT ?)",
                (excess,),
            )
            self._conn.commit()

    def flush(self) -> None:
        if self._max_rows:
            self._prune()
        self._conn.commit()

    def close(self) -> None:
        self.flush()
        self._conn.close()

    def get_stats(self) -> BackendStats:
        return BackendStats(
            bytes_written=self._bytes_written,
            event_count=self._event_count,
            backend_type="sqlite",
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
        conditions = []
        params: list = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if agent_id:
            conditions.append("agent_name = ?")
            params.append(agent_id)
        if from_ts is not None:
            conditions.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts is not None:
            conditions.append("timestamp <= ?")
            params.append(to_ts)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM {self._table}{where} ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(sql, params)
        for row in cursor:
            yield TelemetryEvent(
                event_id=row[0],
                timestamp=row[1],
                session_id=row[2],
                trace_id=row[3],
                span_id=row[4],
                event_type=row[5],
                agent_name=row[6],
                tool_name=row[7],
                model_name=row[8],
                framework=row[9],
                host=row[10],
                data=json.loads(row[11]) if row[11] else {},
                library_version=row[12],
            )
