#!/usr/bin/env bash
# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
# uat-02-runtime-props.sh — UAT-02: Linux runtime property confirmations.
#
# Purpose: Validate three deferred v4.0 runtime confirmations on a real Linux host:
#   CHECK A — Debounce latency: write event to session.jsonl, confirm it appears
#             in events.jsonl within 120ms (target from REQUIREMENTS.md UAT-02)
#   CHECK B — PollWatcher promotion: reduce inotify watch limit via sysctl (requires
#             sudo), restart forwarder, confirm "PollWatcher fallback is now active"
#             appears in stderr within 10s
#   CHECK C — Rotation dedup: rename session file mid-tail, write new content,
#             confirm no duplicates from before rotation and new events arrive
#
# Platform: Linux only (uses GNU date +%s%N, sysctl fs.inotify, /proc/sys/fs/inotify)
# Note: CHECK B requires sudo. Without sudo it will be SKIPped.
#
# Prerequisite: cd rust && cargo build --release
#
# Usage:
#   tests/uat/uat-02-runtime-props.sh
#
# Exit codes:
#   0 — all checks PASS (or SKIP)
#   1 — one or more checks FAIL, or setup error

echo "================================================================"
echo "Phase 41 — UAT-02: Linux Runtime Property Confirmations"
echo "Tests debounce latency, PollWatcher promotion, and rotation dedup."
echo "Intended platform: Linux."
echo "Note: CHECK B (PollWatcher promotion) requires sudo."
echo "================================================================"
echo ""

# ─── Binary discovery ────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BINARY="$REPO_ROOT/rust/target/release/agent-telemetry-fwd"

if [[ ! -x "$BINARY" ]]; then
    echo "ERROR: Release binary not found at $BINARY"
    echo "Build first: cd rust && cargo build --release"
    exit 1
fi

echo "Binary: $BINARY"
echo ""

# ─── Temp directory + PID + cleanup trap ─────────────────────────────────────

TMPDIR_BASE=$(mktemp -d)
FWD_PID=""
ORIG_WATCHES=""   # saved before any sysctl change

cleanup() {
    if [[ -n "$FWD_PID" ]] && kill -0 "$FWD_PID" 2>/dev/null; then
        kill -TERM "$FWD_PID" 2>/dev/null || true
        sleep 2
        kill -KILL "$FWD_PID" 2>/dev/null || true
    fi
    wait "$FWD_PID" 2>/dev/null || true
    # Restore inotify watch limit if it was modified
    if [[ -n "$ORIG_WATCHES" ]]; then
        sudo sysctl -w fs.inotify.max_user_watches="$ORIG_WATCHES" > /dev/null 2>&1 || true
    fi
    rm -rf "$TMPDIR_BASE"
}
trap cleanup EXIT

# ─── Create config.toml with explicit JSONL sink ─────────────────────────────

CONFIG_FILE="$TMPDIR_BASE/config.toml"
EVENTS_FILE="$TMPDIR_BASE/events.jsonl"
SESSION_DIR="$TMPDIR_BASE/home/.claude/projects/uat-02"
SESSION_FILE="$SESSION_DIR/session.jsonl"
mkdir -p "$SESSION_DIR"

cat > "$CONFIG_FILE" << EOF
[cursor]
flush_event_count = 1
flush_interval_ms = 50

[sources]

[[sinks]]
kind = "jsonl"
name = "uat-output"
path = "$EVENTS_FILE"
EOF

# Validate config before use
"$BINARY" check-config "$CONFIG_FILE" || { echo "ERROR: config.toml is malformed"; exit 1; }
echo "Config validated: $CONFIG_FILE"
echo ""

# ─── Start forwarder ─────────────────────────────────────────────────────────

echo "Starting forwarder (RUST_LOG=info for PollWatcher detection)..."
HOME="$TMPDIR_BASE/home" USERPROFILE="$TMPDIR_BASE/home" \
    RUST_LOG="info" \
    "$BINARY" run --config "$CONFIG_FILE" \
    > "$TMPDIR_BASE/fwd.stdout" \
    2> "$TMPDIR_BASE/fwd.stderr" &
FWD_PID=$!
echo "Forwarder PID: $FWD_PID"
# Sleep 3s: ensures poll task has fired once and inotify watches are established
# (avoids 2s polling artifact in latency measurement — RESEARCH.md Pitfall 2)
sleep 3
echo ""

# ─── FAIL accumulator ────────────────────────────────────────────────────────

FAIL=0

# ─── CHECK A: Debounce latency (target <=120ms) ──────────────────────────────

echo "--- CHECK A: Debounce latency ---"
LATENCY_MS=""
# GNU date +%s%N — nanosecond precision (Linux only, safe for this Linux-only script)
BEFORE_NS=$(date +%s%N)
INITIAL_LINES=$(wc -l < "$EVENTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)

# Append synthetic Claude assistant event to session file
echo '{"type":"assistant","message":{"id":"msg_UAT02","model":"claude-opus-4-5","content":[{"type":"text","text":"UAT-02 debounce probe"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}},"sessionId":"01UAT02TEST","timestamp":"2026-01-01T00:00:00Z"}' >> "$SESSION_FILE"

# Poll events.jsonl in a tight loop with 5s deadline
DEADLINE=$(( $(date +%s) + 5 ))
while [[ $(date +%s) -lt $DEADLINE ]]; do
    CURRENT_LINES=$(wc -l < "$EVENTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)
    if [[ "$CURRENT_LINES" -gt "$INITIAL_LINES" ]]; then
        AFTER_NS=$(date +%s%N)
        LATENCY_MS=$(( (AFTER_NS - BEFORE_NS) / 1000000 ))
        break
    fi
    sleep 0.01
done

if [[ -z "$LATENCY_MS" ]]; then
    echo "CHECK A [FAIL]: No new event in events.jsonl within 5s deadline"
    FAIL=1
elif [[ "$LATENCY_MS" -le 120 ]]; then
    echo "CHECK A [PASS]: debounce latency ${LATENCY_MS}ms (target <=120ms)"
else
    echo "CHECK A [FAIL]: debounce latency ${LATENCY_MS}ms exceeds 120ms target"
    FAIL=1
fi
echo ""

# ─── CHECK B: PollWatcher promotion via sysctl ───────────────────────────────

echo "--- CHECK B: PollWatcher promotion ---"
if ! sudo -n sysctl -w fs.inotify.max_user_watches=8 > /dev/null 2>&1; then
    echo "CHECK B [SKIP]: sudo not available; cannot reduce inotify watch limit"
else
    ORIG_WATCHES=$(cat /proc/sys/fs/inotify/max_user_watches)
    sudo sysctl -w fs.inotify.max_user_watches=8 > /dev/null
    echo "  inotify max_user_watches set to 8 (was $ORIG_WATCHES)"

    # Restart forwarder under constrained watch limit
    if [[ -n "$FWD_PID" ]] && kill -0 "$FWD_PID" 2>/dev/null; then
        kill -TERM "$FWD_PID" 2>/dev/null || true
        sleep 2
        kill -KILL "$FWD_PID" 2>/dev/null || true
    fi
    wait "$FWD_PID" 2>/dev/null || true
    FWD_PID=""
    > "$TMPDIR_BASE/fwd.stderr"   # clear for fresh grep

    HOME="$TMPDIR_BASE/home" USERPROFILE="$TMPDIR_BASE/home" \
        RUST_LOG="info" \
        "$BINARY" run --config "$CONFIG_FILE" \
        > "$TMPDIR_BASE/fwd.stdout" \
        2> "$TMPDIR_BASE/fwd.stderr" &
    FWD_PID=$!
    echo "  Forwarder restarted (PID=$FWD_PID). Waiting 10s for promotion..."
    # Promotion fires after error_counter >= 3, checked every 2s (claude_code.rs line 163)
    sleep 10

    PROMOTED=$(grep -c "PollWatcher fallback is now active" "$TMPDIR_BASE/fwd.stderr" 2>/dev/null || echo 0)

    # Restore inotify watch limit and clear ORIG_WATCHES to prevent double-restore in cleanup
    sudo sysctl -w fs.inotify.max_user_watches="$ORIG_WATCHES" > /dev/null
    ORIG_WATCHES=""

    if [[ "$PROMOTED" -ge 1 ]]; then
        echo "CHECK B [PASS]: PollWatcher promotion confirmed within 10s"
    else
        echo "CHECK B [FAIL]: PollWatcher promotion not detected in stderr"
        echo "  Expected: 'PollWatcher fallback is now active'"
        echo "  Stderr tail:"
        tail -5 "$TMPDIR_BASE/fwd.stderr" 2>/dev/null | sed 's/^/    /' || true
        FAIL=1
    fi
fi
echo ""

# ─── CHECK C: Rotation dedup ─────────────────────────────────────────────────

echo "--- CHECK C: Rotation dedup ---"
# Ensure forwarder is running (restart if killed for Check B)
if [[ -z "$FWD_PID" ]] || ! kill -0 "$FWD_PID" 2>/dev/null; then
    HOME="$TMPDIR_BASE/home" USERPROFILE="$TMPDIR_BASE/home" \
        RUST_LOG="info" \
        "$BINARY" run --config "$CONFIG_FILE" \
        > "$TMPDIR_BASE/fwd.stdout" \
        2>> "$TMPDIR_BASE/fwd.stderr" &
    FWD_PID=$!
    echo "  Forwarder restarted for Check C (PID=$FWD_PID)..."
    sleep 3
fi

LINES_BEFORE=$(wc -l < "$EVENTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)

# Rename session file mid-tail (simulates log rotation)
mv "$SESSION_FILE" "${SESSION_FILE}.1"
sleep 1   # give forwarder a moment to detect the rename

# Write a new session event with different ID to fresh session file
echo '{"type":"assistant","message":{"id":"msg_UAT02_POST_ROTATION","model":"claude-opus-4-5","content":[{"type":"text","text":"post-rotation event"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}},"sessionId":"01UAT02TEST","timestamp":"2026-01-01T00:00:01Z"}' > "$SESSION_FILE"
sleep 3

LINES_AFTER=$(wc -l < "$EVENTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)
NEW_EVENTS=$(( LINES_AFTER - LINES_BEFORE ))

# Count occurrences of original probe msg_UAT02 — should be exactly 1 (from Check A)
# No new copies should appear after rotation (dedup confirmation)
DUPE_COUNT=$(grep -c 'msg_UAT02"' "$EVENTS_FILE" 2>/dev/null || echo 0)

if [[ "$DUPE_COUNT" -le 1 ]] && [[ "$NEW_EVENTS" -ge 1 ]]; then
    echo "CHECK C [PASS]: rotation dedup confirmed (${NEW_EVENTS} new events, original msg seen ${DUPE_COUNT} time(s))"
else
    echo "CHECK C [FAIL]: duplicate_count=$DUPE_COUNT new_events=$NEW_EVENTS"
    echo "  Expected: dupe_count <= 1 AND new_events >= 1"
    FAIL=1
fi
echo ""

# ─── Final verdict ────────────────────────────────────────────────────────────

if [[ "$FAIL" -eq 0 ]]; then
    echo "UAT-02 [PASS]: Linux runtime property confirmations — all checks passed"
    exit 0
else
    echo "UAT-02 [FAIL]: One or more checks failed — see above"
    exit 1
fi
