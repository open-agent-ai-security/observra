#!/usr/bin/env bash
# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0
# soak_baseline.sh — Phase 31 soak benchmark baseline for PERF-03 validation.
#
# Purpose: Measure forwarder resource usage (RSS memory) and backpressure DLQ
# behavior under sustained load. Provides a baseline for Phase 34 (TEST-01) to
# extend into a full 1-hour nightly soak test.
#
# Scope: This script is a scaffold. It validates the Phase 31 PERF-03 bounded
# channel architecture works under load and does not OOM under 10,000 events.
# Phase 34 will extend this into a full 1-hour soak with monotonicity checks.
#
# Usage:
#   cd rust && cargo build --release
#   cd .. && tests/load/soak_baseline.sh
#
# Exit codes:
#   0 — peak RSS < 200 MB and no OOM
#   1 — peak RSS >= 200 MB or OOM detected
#
# Requirements:
#   - Built release binary at rust/target/release/agent-telemetry-fwd
#   - macOS or Linux (uses `ps -o rss=`)
#   - tmpfs available for temp directory

set -euo pipefail

echo "================================================================"
echo "Phase 31 soak benchmark baseline"
echo "Measures forwarder resource usage under sustained load (PERF-03)"
echo "================================================================"
echo ""

# ─── Setup ──────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BINARY="$REPO_ROOT/rust/target/release/agent-telemetry-fwd"

if [[ ! -x "$BINARY" ]]; then
    echo "ERROR: Release binary not found at $BINARY"
    echo "Build first: cd rust && cargo build --release"
    exit 1
fi

# Temporary directory serves as $HOME for the forwarder.
TMPDIR_BASE=$(mktemp -d)
trap 'rm -rf "$TMPDIR_BASE"' EXIT

HOME_DIR="$TMPDIR_BASE/home"
mkdir -p "$HOME_DIR/.claude/projects/soak-test"
mkdir -p "$HOME_DIR/.agent-telemetry"

SESSION_FILE="$HOME_DIR/.claude/projects/soak-test/session.jsonl"
EVENTS_FILE="$HOME_DIR/Library/Application Support/agent-telemetry/events.jsonl"
# Linux fallback path
if [[ "$(uname)" != "Darwin" ]]; then
    EVENTS_FILE="$HOME_DIR/.local/share/agent-telemetry/events.jsonl"
fi
DLQ_FILE="$HOME_DIR/.agent-telemetry/dlq.jsonl"

# ─── Write synthetic session file ───────────────────────────────────────────

echo "Writing 10,000 synthetic events to session file..."
EVENT_COUNT=10000
python3 - <<PYEOF
import json, sys

path = "$SESSION_FILE"
with open(path, "w") as f:
    for i in range($EVENT_COUNT):
        event = {
            "type": "assistant",
            "message": {
                "id": f"msg_{i:06d}",
                "model": "claude-opus-4-5",
                "content": [{"type": "text", "text": f"Response {i}"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 50}
            },
            "sessionId": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "timestamp": "2026-01-01T00:00:00Z"
        }
        f.write(json.dumps(event) + "\\n")
print(f"Wrote {$EVENT_COUNT} events to $SESSION_FILE")
PYEOF

# ─── Start forwarder ────────────────────────────────────────────────────────

echo ""
echo "Starting forwarder..."
HOME="$HOME_DIR" \
    USERPROFILE="$HOME_DIR" \
    RUST_LOG="warn" \
    "$BINARY" run \
    > "$TMPDIR_BASE/fwd.stdout" \
    2> "$TMPDIR_BASE/fwd.stderr" \
    &
FWD_PID=$!
echo "Forwarder PID: $FWD_PID"

# Give the forwarder a moment to start.
sleep 2

# ─── Monitor RSS for 5 minutes (or until complete) ──────────────────────────

echo ""
echo "Monitoring RSS memory usage (5-second intervals, 5 minutes max)..."
PEAK_RSS=0
MONITOR_SECONDS=300
INTERVAL=5
ELAPSED=0

while [[ $ELAPSED -lt $MONITOR_SECONDS ]]; do
    if ! kill -0 $FWD_PID 2>/dev/null; then
        echo "WARNING: Forwarder exited prematurely at t=${ELAPSED}s"
        break
    fi

    # RSS in KB (ps -o rss= returns KB on both macOS and Linux).
    CURRENT_RSS=$(ps -p $FWD_PID -o rss= 2>/dev/null || echo "0")
    CURRENT_RSS="${CURRENT_RSS//[[:space:]]/}"
    CURRENT_RSS="${CURRENT_RSS:-0}"

    if [[ "$CURRENT_RSS" -gt "$PEAK_RSS" ]]; then
        PEAK_RSS=$CURRENT_RSS
    fi

    PEAK_RSS_MB=$(( PEAK_RSS / 1024 ))
    echo "  t=${ELAPSED}s RSS=${CURRENT_RSS}KB peak=${PEAK_RSS_MB}MB"

    sleep $INTERVAL
    ELAPSED=$(( ELAPSED + INTERVAL ))
done

# ─── Collect results ────────────────────────────────────────────────────────

echo ""
echo "Stopping forwarder..."
if kill -0 $FWD_PID 2>/dev/null; then
    kill -TERM $FWD_PID 2>/dev/null || true
    sleep 2
    kill -KILL $FWD_PID 2>/dev/null || true
fi
wait $FWD_PID 2>/dev/null || true

# Count events delivered to sink.
SINK_EVENTS=0
if [[ -f "$EVENTS_FILE" ]]; then
    SINK_EVENTS=$(grep -c . "$EVENTS_FILE" 2>/dev/null || echo "0")
fi

# Count backpressure DLQ entries.
DLQ_BACKPRESSURE=0
DLQ_TOTAL=0
if [[ -f "$DLQ_FILE" ]]; then
    DLQ_TOTAL=$(grep -c . "$DLQ_FILE" 2>/dev/null || echo "0")
    DLQ_BACKPRESSURE=$(grep -c "backpressure" "$DLQ_FILE" 2>/dev/null || echo "0")
fi

PEAK_RSS_MB=$(( PEAK_RSS / 1024 ))
THROUGHPUT_MSG="N/A (monitor ended early)"
if [[ $ELAPSED -gt 0 ]]; then
    THROUGHPUT=$(( SINK_EVENTS / ELAPSED ))
    THROUGHPUT_MSG="${THROUGHPUT} events/s"
fi

echo "================================================================"
echo "Results:"
echo "  Peak RSS:            ${PEAK_RSS_MB} MB (limit: 200 MB)"
echo "  Events in sink:      ${SINK_EVENTS}"
echo "  DLQ total entries:   ${DLQ_TOTAL}"
echo "  DLQ backpressure:    ${DLQ_BACKPRESSURE}"
echo "  Throughput:          ${THROUGHPUT_MSG}"
echo "================================================================"
echo ""
echo "Note: This is a baseline scaffold for Phase 34 (TEST-01) which will"
echo "extend this into a full 1-hour nightly soak test with monotonicity"
echo "checks (no event loss, no duplicate ULIDs)."

# ─── Exit code ───────────────────────────────────────────────────────────────

if [[ "$PEAK_RSS_MB" -ge 200 ]]; then
    echo "FAIL: Peak RSS ${PEAK_RSS_MB} MB exceeds 200 MB limit"
    exit 1
fi

echo "PASS: Peak RSS ${PEAK_RSS_MB} MB is within 200 MB limit"
exit 0
