#!/usr/bin/env bash
# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
# uat-03-wsl-fallback.sh — UAT-03: WSL2 PollWatcher fallback verification.
#
# Purpose: Validate PollWatcher fallback behavior in a WSL2 environment and
# confirm the forwarder emits events correctly after fallback activation.
#   CHECK A — PollWatcher promotion in WSL2: attempt forced promotion via sysctl
#             (if sudo available), or test natural WSL2 inotify behavior
#   CHECK B — Basic event flow verification: write synthetic event to session file,
#             confirm it appears in events.jsonl within 5s
#
# Platform: Intended for WSL2 (Linux kernel with Microsoft integration).
#           Script will warn but continue on non-WSL2 Linux.
#
# Prerequisite: cd rust && cargo build --release
#
# Usage:
#   tests/uat/uat-03-wsl-fallback.sh
#
# Exit codes:
#   0 — all checks PASS (or SKIP)
#   1 — one or more checks FAIL, or setup error

echo "================================================================"
echo "Phase 41 — UAT-03: WSL2 PollWatcher Fallback Verification"
echo "Tests PollWatcher promotion and event flow under WSL2 kernel."
echo "Intended platform: WSL2 (Windows Subsystem for Linux 2)."
echo "================================================================"
echo ""

# ─── WSL2 detection guard ────────────────────────────────────────────────────

if ! grep -qi microsoft /proc/version 2>/dev/null; then
    echo "WARNING: /proc/version does not indicate WSL2 kernel"
    echo "  This script is intended for WSL2. Results may not reflect WSL2 behavior."
    echo ""
else
    echo "WSL2 kernel detected."
    KERNEL=$(uname -r)
    echo "  Kernel: $KERNEL"
    echo ""
fi

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
    # Restore inotify watch limit if modified
    if [[ -n "$ORIG_WATCHES" ]]; then
        sudo sysctl -w fs.inotify.max_user_watches="$ORIG_WATCHES" > /dev/null 2>&1 || true
    fi
    rm -rf "$TMPDIR_BASE"
}
trap cleanup EXIT

# ─── Create config.toml with explicit JSONL sink ─────────────────────────────

CONFIG_FILE="$TMPDIR_BASE/config.toml"
EVENTS_FILE="$TMPDIR_BASE/events.jsonl"
SESSION_DIR="$TMPDIR_BASE/home/.claude/projects/uat-03"
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

# ─── FAIL accumulator ────────────────────────────────────────────────────────

FAIL=0

# ─── CHECK A: PollWatcher promotion in WSL2 ──────────────────────────────────

echo "--- CHECK A: PollWatcher promotion ---"

# WSL2: inotify may already be broken without sysctl; try forced promotion first
FORCED_PROMOTION=0
if sudo -n sysctl -w fs.inotify.max_user_watches=8 > /dev/null 2>&1; then
    ORIG_WATCHES=$(cat /proc/sys/fs/inotify/max_user_watches)
    sudo sysctl -w fs.inotify.max_user_watches=8 > /dev/null
    echo "  sudo available: forced watch limit exhaustion (max_user_watches=8, was $ORIG_WATCHES)"
    FORCED_PROMOTION=1
else
    echo "  sudo unavailable — testing natural WSL2 inotify behavior"
    FORCED_PROMOTION=0
fi

# Start forwarder and wait 10s for promotion
echo "  Starting forwarder (RUST_LOG=info, waiting 10s for potential promotion)..."
HOME="$TMPDIR_BASE/home" USERPROFILE="$TMPDIR_BASE/home" \
    RUST_LOG="info" \
    "$BINARY" run --config "$CONFIG_FILE" \
    > "$TMPDIR_BASE/fwd.stdout" \
    2> "$TMPDIR_BASE/fwd.stderr" &
FWD_PID=$!
# Promotion fires after error_counter >= 3, checked every 2s (claude_code.rs line 163)
sleep 10

PROMOTED=$(grep -c "PollWatcher fallback is now active" "$TMPDIR_BASE/fwd.stderr" 2>/dev/null || echo 0)

# Restore inotify watch limit if forced; clear ORIG_WATCHES to prevent double-restore
if [[ "$FORCED_PROMOTION" -eq 1 ]]; then
    sudo sysctl -w fs.inotify.max_user_watches="$ORIG_WATCHES" > /dev/null
    ORIG_WATCHES=""
fi

if [[ "$PROMOTED" -ge 1 ]]; then
    echo "CHECK A [PASS]: PollWatcher promotion confirmed in WSL2 within 10s"
else
    if [[ "$FORCED_PROMOTION" -eq 0 ]]; then
        echo "CHECK A [SKIP]: sudo unavailable; natural WSL2 inotify did not trigger promotion"
        echo "  Document: inotify appears functional in this WSL2 environment"
    else
        echo "CHECK A [FAIL]: PollWatcher promotion not detected despite watch limit exhaustion"
        echo "  Expected: 'PollWatcher fallback is now active' in stderr"
        echo "  Stderr tail:"
        tail -5 "$TMPDIR_BASE/fwd.stderr" 2>/dev/null | sed 's/^/    /' || true
        FAIL=1
    fi
fi
echo ""

# ─── CHECK B: Basic event flow verification ──────────────────────────────────

echo "--- CHECK B: Basic event flow ---"
# Ensure forwarder is still running (it should be from Check A)
if [[ -z "$FWD_PID" ]] || ! kill -0 "$FWD_PID" 2>/dev/null; then
    echo "  Forwarder not running — restarting for event flow check..."
    HOME="$TMPDIR_BASE/home" USERPROFILE="$TMPDIR_BASE/home" \
        RUST_LOG="info" \
        "$BINARY" run --config "$CONFIG_FILE" \
        > "$TMPDIR_BASE/fwd.stdout" \
        2>> "$TMPDIR_BASE/fwd.stderr" &
    FWD_PID=$!
    sleep 3
fi

INITIAL_LINES=$(wc -l < "$EVENTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)

# Write a synthetic event to session file
echo '{"type":"assistant","message":{"id":"msg_UAT03","model":"claude-opus-4-5","content":[{"type":"text","text":"UAT-03 event flow probe"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}},"sessionId":"01UAT03TEST","timestamp":"2026-01-01T00:00:00Z"}' >> "$SESSION_FILE"

# Wait up to 5s for event to appear in events.jsonl
DEADLINE=$(( $(date +%s) + 5 ))
EVENT_APPEARED=0
while [[ $(date +%s) -lt $DEADLINE ]]; do
    CURRENT_LINES=$(wc -l < "$EVENTS_FILE" 2>/dev/null | tr -d ' ' || echo 0)
    if [[ "$CURRENT_LINES" -gt "$INITIAL_LINES" ]]; then
        EVENT_APPEARED=1
        break
    fi
    sleep 0.1
done

if [[ "$EVENT_APPEARED" -eq 1 ]]; then
    echo "CHECK B [PASS]: Event appeared in events.jsonl within 5s"
else
    echo "CHECK B [FAIL]: No new event in events.jsonl within 5s deadline"
    echo "  events.jsonl lines: $INITIAL_LINES (unchanged)"
    FAIL=1
fi
echo ""

# ─── WSL2 environment documentation ──────────────────────────────────────────

echo "--- WSL2 Environment Info (for UAT report) ---"
echo "  Kernel: $(uname -r)"
echo "  /proc/version: $(cat /proc/version 2>/dev/null | head -1 || echo 'not available')"
echo "  inotify max_user_watches: $(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo 'not available')"
echo ""

# ─── Final verdict ────────────────────────────────────────────────────────────

if [[ "$FAIL" -eq 0 ]]; then
    echo "UAT-03 [PASS]: WSL2 PollWatcher fallback verification — all checks passed"
    exit 0
else
    echo "UAT-03 [FAIL]: One or more checks failed — see above"
    exit 1
fi
