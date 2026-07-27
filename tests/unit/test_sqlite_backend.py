# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for SQLite storage backend."""

import os
import sqlite3
import stat

import pytest

from observra.backends.sqlite import SQLiteBackend
from observra.core.context import initialize_session, initialize_trace
from observra.core.events import create_event


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_telemetry.db"


@pytest.fixture
def backend(db_path):
    initialize_trace()
    initialize_session()
    be = SQLiteBackend(path=db_path)
    yield be
    be.close()


def _make_event(event_type="model_response", ts=None):
    initialize_trace()
    initialize_session()
    e = create_event(event_type=event_type, framework="test", model_name="test-model")
    if ts is not None:
        object.__setattr__(e, "timestamp", ts)
    return e


def test_creates_db_with_restrictive_permissions(db_path):
    be = SQLiteBackend(path=db_path)
    be.close()
    mode = stat.S_IMODE(os.stat(db_path).st_mode)
    assert mode == 0o600


def test_wal_mode_enabled(db_path):
    be = SQLiteBackend(path=db_path)
    conn = sqlite3.connect(str(db_path))
    result = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    be.close()
    assert result == "wal"


def test_write_and_query_roundtrip(backend, db_path):
    event = _make_event()
    backend.write(event)
    backend.flush()

    results = list(backend.query())
    assert len(results) == 1
    assert results[0].event_id == event.event_id
    assert results[0].event_type == event.event_type
    assert results[0].session_id == event.session_id
    assert results[0].model_name == "test-model"


def test_query_by_event_type(backend):
    backend.write(_make_event(event_type="model_response"))
    backend.write(_make_event(event_type="tool_start"))
    backend.write(_make_event(event_type="model_response"))
    backend.flush()

    results = list(backend.query(event_type="tool_start"))
    assert len(results) == 1
    assert results[0].event_type == "tool_start"


def test_query_by_time_range(backend):
    backend.write(_make_event(ts=100.0))
    backend.write(_make_event(ts=200.0))
    backend.write(_make_event(ts=300.0))
    backend.flush()

    results = list(backend.query(from_ts=150.0, to_ts=250.0))
    assert len(results) == 1
    assert results[0].timestamp == 200.0


def test_max_rows_pruning(db_path):
    be = SQLiteBackend(path=db_path, max_rows=50)
    initialize_trace()
    initialize_session()

    for i in range(150):
        be.write(_make_event(ts=float(i)))

    be.flush()

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    be.close()

    assert count <= 50


def test_get_stats(backend):
    backend.write(_make_event(ts=100.0))
    backend.write(_make_event(ts=200.0))

    stats = backend.get_stats()
    assert stats["backend_type"] == "sqlite"
    assert stats["event_count"] == 2
    assert stats["oldest_event_ts"] == 100.0
    assert stats["newest_event_ts"] == 200.0


def test_indexes_exist(backend, db_path):
    conn = sqlite3.connect(str(db_path))
    indexes = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'").fetchall()
    conn.close()

    index_names = {row[0] for row in indexes}
    assert "idx_events_session_id" in index_names
    assert "idx_events_event_type" in index_names
    assert "idx_events_timestamp" in index_names


def test_custom_table_name(db_path):
    be = SQLiteBackend(path=db_path, table_name="my_events")
    initialize_trace()
    initialize_session()
    be.write(_make_event())
    be.flush()

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM my_events").fetchone()[0]
    conn.close()
    be.close()

    assert count == 1


def test_initialize_with_sqlite_backend(tmp_path):
    import observra

    db = tmp_path / "init_test.db"
    observra.initialize(backend="sqlite", path=str(db))
    assert db.exists()
