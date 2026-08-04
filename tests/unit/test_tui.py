# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Observra TUI dashboard."""

import json
import sqlite3

import pytest

pytest.importorskip("textual")

from observra.tui.app import ObservraWatch, _format_detail, _format_ts


@pytest.fixture
def sample_db(tmp_path):
    """Create a SQLite DB with sample telemetry events."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            session_id TEXT NOT NULL,
            trace_id TEXT,
            span_id TEXT,
            event_type TEXT NOT NULL,
            agent_name TEXT,
            tool_name TEXT,
            model_name TEXT,
            framework TEXT,
            host TEXT,
            data TEXT,
            library_version TEXT
        )
    """)
    events = [
        (
            "e1",
            1700000001.0,
            "sess-1",
            "t1",
            "s1",
            "session_start",
            "my-agent",
            None,
            None,
            "test",
            "host1",
            "{}",
            "1.0.8",
        ),
        (
            "e2",
            1700000002.0,
            "sess-1",
            "t1",
            "s2",
            "model_request",
            "my-agent",
            None,
            "gemini-2.5-flash",
            "test",
            "host1",
            json.dumps({"input_tokens": 1200}),
            "1.0.8",
        ),
        (
            "e3",
            1700000004.0,
            "sess-1",
            "t1",
            "s3",
            "model_response",
            "my-agent",
            None,
            "gemini-2.5-flash",
            "test",
            "host1",
            json.dumps({"input_tokens": 1200, "output_tokens": 310, "cost_usd": 0.012, "duration_ms": 2100}),
            "1.0.8",
        ),
        (
            "e4",
            1700000004.5,
            "sess-1",
            "t1",
            "s4",
            "tool_start",
            "my-agent",
            "read_file",
            None,
            "test",
            "host1",
            "{}",
            "1.0.8",
        ),
        (
            "e5",
            1700000005.0,
            "sess-1",
            "t1",
            "s5",
            "tool_end",
            "my-agent",
            "read_file",
            None,
            "test",
            "host1",
            json.dumps({"duration_ms": 340}),
            "1.0.8",
        ),
        (
            "e6",
            1700000008.0,
            "sess-1",
            "t1",
            "s6",
            "model_response",
            "my-agent",
            None,
            "gemini-2.5-flash",
            "test",
            "host1",
            json.dumps({"input_tokens": 3400, "output_tokens": 180, "cost_usd": 0.022, "duration_ms": 2800}),
            "1.0.8",
        ),
        (
            "e7",
            1700000009.0,
            "sess-1",
            "t1",
            "s7",
            "model_error",
            "my-agent",
            None,
            "gemini-2.5-flash",
            "test",
            "host1",
            json.dumps({"error_message": "Rate limit exceeded"}),
            "1.0.8",
        ),
        (
            "e8",
            1700000010.0,
            "sess-1",
            "t1",
            "s8",
            "session_end",
            "my-agent",
            None,
            None,
            "test",
            "host1",
            json.dumps({"session_cost_usd": 0.034}),
            "1.0.8",
        ),
    ]
    conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", events)
    conn.commit()
    conn.close()
    return db_path


def test_format_ts():
    assert _format_ts(1700000001.0) == "22:13:21"


def test_format_detail_model_response():
    data = {"cost_usd": 0.012, "duration_ms": 2100, "output_tokens": 310}
    result = _format_detail("model_response", data)
    assert "$0.0120" in result
    assert "2.1s" in result
    assert "310 out" in result


def test_format_detail_model_request():
    assert "1,200 tokens" in _format_detail("model_request", {"input_tokens": 1200})


def test_format_detail_tool_end():
    assert "340ms" in _format_detail("tool_end", {"duration_ms": 340})


def test_format_detail_session_end():
    assert "$0.0340 total" in _format_detail("session_end", {"session_cost_usd": 0.034})


def test_format_detail_error():
    assert "Rate limit" in _format_detail("model_error", {"error_message": "Rate limit exceeded"})


@pytest.mark.asyncio
async def test_tui_loads_events(sample_db):
    app = ObservraWatch(db_path=str(sample_db), poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(delay=0.5)

        summary = app.query_one("SummaryBar")
        assert summary.event_count == 8
        assert summary.agent_name == "my-agent"
        assert summary.session_id == "sess-1"
        assert summary.total_cost == pytest.approx(0.034, abs=0.001)
        assert summary.tokens_in == 5800
        assert summary.tokens_out == 490
        assert summary.errors == 1

        table = app.query_one("DataTable")
        assert table.row_count == 8


@pytest.mark.asyncio
async def test_tui_graceful_missing_db(tmp_path):
    app = ObservraWatch(db_path=str(tmp_path / "nonexistent.db"), poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(delay=0.3)

        summary = app.query_one("SummaryBar")
        assert summary.event_count == 0


@pytest.mark.asyncio
async def test_tui_incremental_polling(sample_db):
    app = ObservraWatch(db_path=str(sample_db), poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(delay=0.5)

        # Add more events after initial load
        conn = sqlite3.connect(str(sample_db))
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "e9",
                1700000011.0,
                "sess-1",
                "t1",
                "s9",
                "model_response",
                "my-agent",
                None,
                "gemini-2.5-flash",
                "test",
                "host1",
                json.dumps({"input_tokens": 500, "output_tokens": 100, "cost_usd": 0.005}),
                "1.0.8",
            ),
        )
        conn.commit()
        conn.close()

        await pilot.pause(delay=0.5)

        summary = app.query_one("SummaryBar")
        assert summary.event_count == 9
        assert summary.total_cost == pytest.approx(0.039, abs=0.001)
