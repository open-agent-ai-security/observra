# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""How to instrument a custom agent framework with observra.emit().

Install:
    pip install observra

No extras needed — emit() is part of the core package.

This example simulates a multi-step agent session using a custom
orchestration layer. Every lifecycle event is captured without needing
a framework-specific adapter.
"""

import observra

# ── Step 1: Initialize the pipeline ───────────────────────────────

observra.initialize(backend="jsonl", path="custom_agent_telemetry.jsonl")

# ── Step 2: Set session identity ──────────────────────────────────

observra.initialize_session("demo-session-2026-08-05")

# ── Step 3: Emit events from your agent's lifecycle ───────────────

# Session starts
observra.emit(
    "session_start",
    agent_name="research-agent",
    framework="custom",
)

# User sends a message (injection detection runs automatically)
observra.emit(
    "user_message",
    agent_name="research-agent",
    framework="custom",
    user_message_text="Find recent papers on transformer architecture improvements",
)

# Agent calls the model
observra.emit(
    "model_response",
    agent_name="research-agent",
    model_name="deepseek-v4-pro",
    framework="custom",
    input_tokens=1200,
    output_tokens=340,
    cost_usd=0.023,
    duration_ms=2100,
)

# Agent uses a tool
observra.emit(
    "tool_start",
    agent_name="research-agent",
    tool_name="arxiv_search",
    framework="custom",
)

observra.emit(
    "tool_end",
    agent_name="research-agent",
    tool_name="arxiv_search",
    framework="custom",
    duration_ms=850,
)

# Agent calls the model again with tool results
observra.emit(
    "model_response",
    agent_name="research-agent",
    model_name="deepseek-v4-pro",
    framework="custom",
    input_tokens=3400,
    output_tokens=520,
    cost_usd=0.041,
    duration_ms=3200,
)

# Agent hands off to a sub-agent
observra.emit(
    "agent_start",
    agent_name="summarizer",
    framework="custom",
    source_agent="research-agent",
)

observra.emit(
    "model_response",
    agent_name="summarizer",
    model_name="gpt-4o-mini",
    framework="custom",
    input_tokens=4200,
    output_tokens=280,
    cost_usd=0.003,
    duration_ms=1800,
)

# Session ends
observra.emit(
    "session_end",
    agent_name="research-agent",
    framework="custom",
    session_cost_usd=0.067,
)

# ── View results ──────────────────────────────────────────────────

stats = observra.get_stats()
print("Session complete!")
print(f"  Events processed: {stats.get('events_processed', 0)}")
print("  File: custom_agent_telemetry.jsonl")
print()
print("View events:")
print("  cat custom_agent_telemetry.jsonl | python -m json.tool")
print()
print("Or use the TUI dashboard:")
print("  # First, run with SQLite backend instead:")
print("  #   observra.initialize(backend='sqlite', path='telemetry.db')")
print("  # Then: python -m observra.tui --db telemetry.db")
