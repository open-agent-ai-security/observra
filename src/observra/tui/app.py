# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Observra Watch — live terminal dashboard powered by Textual."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static

_EVENT_COLORS = {
    "session_start": "bold white",
    "session_end": "bold white",
    "model_request": "cyan",
    "model_response": "green",
    "tool_start": "blue",
    "tool_end": "blue",
    "user_message": "magenta",
    "agent_start": "white",
    "agent_end": "white",
    "model_error": "bold red",
    "tool_error": "bold red",
    "cost_threshold_exceeded": "bold yellow",
}


def _format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def _format_detail(event_type: str, data: dict) -> str:
    if event_type == "model_response":
        parts = []
        if data.get("cost_usd"):
            parts.append(f"${data['cost_usd']:.4f}")
        if data.get("duration_ms"):
            parts.append(f"{data['duration_ms'] / 1000:.1f}s")
        if data.get("output_tokens"):
            parts.append(f"{data['output_tokens']} out")
        return "  ".join(parts)
    elif event_type == "model_request":
        tokens = data.get("input_tokens")
        return f"{tokens:,} tokens" if tokens else ""
    elif event_type == "tool_end":
        ms = data.get("duration_ms")
        return f"{ms:.0f}ms" if ms else ""
    elif event_type == "session_end":
        cost = data.get("session_cost_usd")
        return f"${cost:.4f} total" if cost else ""
    elif event_type == "cost_threshold_exceeded":
        return data.get("message", "")
    elif event_type == "model_error" or event_type == "tool_error":
        return data.get("error_message", "")[:60]
    return ""


class SummaryBar(Static):
    """Top summary bar showing session stats."""

    session_id: reactive[str] = reactive("")
    agent_name: reactive[str] = reactive("")
    event_count: reactive[int] = reactive(0)
    total_cost: reactive[float] = reactive(0.0)
    tokens_in: reactive[int] = reactive(0)
    tokens_out: reactive[int] = reactive(0)
    errors: reactive[int] = reactive(0)

    def render(self) -> str:
        sid = self.session_id[:20] + "..." if len(self.session_id) > 20 else self.session_id
        agent = self.agent_name or "—"
        return (
            f"  Session: [bold]{sid}[/]  │  Agent: [bold]{agent}[/]\n"
            f"  Events: {self.event_count}  │  "
            f"Cost: [green]${self.total_cost:.4f}[/]  │  "
            f"Tokens: {self.tokens_in:,} in / {self.tokens_out:,} out  │  "
            f"Errors: [{'red' if self.errors else 'white'}]{self.errors}[/]"
        )


class ObservraWatch(App):
    """Live telemetry dashboard that polls a SQLite database."""

    TITLE = "Observra Watch"
    CSS = """
    SummaryBar {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }
    DataTable {
        height: 1fr;
    }
    #status {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, db_path: str = "telemetry.db", poll_interval: float = 0.5):
        super().__init__()
        self._db_path = Path(db_path)
        self._poll_interval = poll_interval
        self._conn: sqlite3.Connection | None = None
        self._last_rowid: int = 0
        self._total_cost: float = 0.0
        self._tokens_in: int = 0
        self._tokens_out: int = 0
        self._errors: int = 0
        self._session_id: str = ""
        self._agent_name: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield SummaryBar()
        yield DataTable()
        yield Static("  ▌ waiting for database...", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Time", "Type", "Name/Model", "Detail")
        table.cursor_type = "row"
        self.set_interval(self._poll_interval, self._poll)

    def _connect(self) -> bool:
        if self._conn is not None:
            return True
        if not self._db_path.exists():
            return False
        try:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self.query_one("#status", Static).update(
                "  ▌ watching... (polling every {:.1f}s)".format(self._poll_interval)
            )
            return True
        except Exception:
            return False

    def _poll(self) -> None:
        if not self._connect():
            return

        try:
            cursor = self._conn.execute(
                "SELECT rowid, timestamp, event_type, agent_name, tool_name, "
                "model_name, data, session_id FROM events WHERE rowid > ? ORDER BY rowid ASC LIMIT 100",
                (self._last_rowid,),
            )
            rows = cursor.fetchall()
        except Exception:
            return

        if not rows:
            return

        table = self.query_one(DataTable)
        summary = self.query_one(SummaryBar)

        for row in rows:
            rowid, ts, event_type, agent_name, tool_name, model_name, data_json, session_id = row
            self._last_rowid = rowid

            data = json.loads(data_json) if data_json else {}

            if session_id and not self._session_id:
                self._session_id = session_id
            if agent_name and not self._agent_name:
                self._agent_name = agent_name

            # Accumulate stats
            if data.get("cost_usd"):
                self._total_cost += float(data["cost_usd"])
            if data.get("input_tokens"):
                self._tokens_in += int(data["input_tokens"])
            if data.get("output_tokens"):
                self._tokens_out += int(data["output_tokens"])
            if "error" in event_type:
                self._errors += 1

            # Format row
            time_str = _format_ts(ts)
            name = model_name or tool_name or agent_name or "—"
            detail = _format_detail(event_type, data)
            color = _EVENT_COLORS.get(event_type, "white")

            table.add_row(
                f"[{color}]{time_str}[/]",
                f"[{color}]{event_type}[/]",
                f"[{color}]{name}[/]",
                f"[{color}]{detail}[/]",
            )

        # Auto-scroll to bottom
        table.scroll_end()

        # Update summary
        summary.session_id = self._session_id
        summary.agent_name = self._agent_name
        summary.event_count += len(rows)
        summary.total_cost = self._total_cost
        summary.tokens_in = self._tokens_in
        summary.tokens_out = self._tokens_out
        summary.errors = self._errors

    def action_refresh(self) -> None:
        self._poll()
