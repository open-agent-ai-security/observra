#!/usr/bin/env bash
# soak_1hr.sh — 1-hour soak test orchestrator for BEAM agent-telemetry-fwd.
#
# Purpose: TEST-01 production-grade soak test. Extends the Phase 31 scaffold
# (soak_baseline.sh) to a full 1-hour run with:
#   - Sustained 100 events/sec via event_generator.py
#   - RSS memory sampling every 30 seconds
#   - Post-run analysis via analyze_soak.py (peak RSS, monotonicity, p99 latency)
#   - Structured PASS/FAIL report with per-metric verdicts
#
# Usage:
#   cd rust && cargo build --release && cd ..
#   tests/load/soak_1hr.sh
#
# Overridable via environment variables:
#   SOAK_DURATION   — seconds to run (default: 3600)
#   SOAK_RATE       — events/sec for generator (default: 100)
#   SOAK_MAX_RSS_MB — peak RSS failure threshold in MB (default: 200)
#   SOAK_MAX_P99_MS — p99 latency failure threshold in ms (default: 500)
#
# Exit codes:
#   0 — all metrics PASS (see analyze_soak.py for per-metric thresholds)
#   1 — one or more metrics FAIL, or script setup error

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

SOAK_DURATION=${SOAK_DURATION:-3600}     # seconds (1 hour)
SOAK_RATE=${SOAK_RATE:-100}              # events/sec
SOAK_MAX_RSS_MB=${SOAK_MAX_RSS_MB:-200}  # peak RSS limit (MB)
SOAK_MAX_P99_MS=${SOAK_MAX_P99_MS:-500}  # p99 latency limit (ms)

RSS_INTERVAL=30   # seconds between RSS samples; MONITOR_SECONDS=3600 (SOAK_DURATION)
DRAIN_SECONDS=60  # extra time after SOAK_DURATION to let forwarder flush

echo "================================================================"
echo "Phase 34 — 1-Hour Soak Test (TEST-01)"
echo "Measures forwarder resource usage under sustained load"
echo ""
echo "Configuration:"
echo "  Duration:     ${SOAK_DURATION}s ($(( SOAK_DURATION / 60 )) minutes)"
echo "  Event rate:   ${SOAK_RATE} events/sec"
echo "  Max RSS:      ${SOAK_MAX_RSS_MB} MB"
echo "  Max p99:      ${SOAK_MAX_P99_MS} ms"
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

# ─── Temp directory + cleanup trap ───────────────────────────────────────────

TMPDIR_BASE=$(mktemp -d)
GEN_PID=""
FWD_PID=""

cleanup() {
    echo ""
    echo "Cleaning up..."
    if [[ -n "$GEN_PID" ]] && kill -0 "$GEN_PID" 2>/dev/null; then
        kill -TERM "$GEN_PID" 2>/dev/null || true
        sleep 1
        kill -KILL "$GEN_PID" 2>/dev/null || true
    fi
    if [[ -n "$FWD_PID" ]] && kill -0 "$FWD_PID" 2>/dev/null; then
        kill -TERM "$FWD_PID" 2>/dev/null || true
        sleep 2
        kill -KILL "$FWD_PID" 2>/dev/null || true
    fi
    wait "$GEN_PID" 2>/dev/null || true
    wait "$FWD_PID" 2>/dev/null || true
    rm -rf "$TMPDIR_BASE"
}
trap cleanup EXIT

# ─── Setup temp HOME ─────────────────────────────────────────────────────────

HOME_DIR="$TMPDIR_BASE/home"
mkdir -p "$HOME_DIR/.claude/projects/soak-test"
mkdir -p "$HOME_DIR/.agent-telemetry"

SESSION_FILE="$HOME_DIR/.claude/projects/soak-test/session.jsonl"
RSS_LOG="$TMPDIR_BASE/rss_log.csv"

# Determine events sink path (matches forwarder platform defaults).
if [[ "$(uname)" == "Darwin" ]]; then
    EVENTS_FILE="$HOME_DIR/Library/Application Support/agent-telemetry/events.jsonl"
    mkdir -p "$HOME_DIR/Library/Application Support/agent-telemetry"
else
    EVENTS_FILE="$HOME_DIR/.local/share/agent-telemetry/events.jsonl"
    mkdir -p "$HOME_DIR/.local/share/agent-telemetry"
fi

# ─── Start event generator ───────────────────────────────────────────────────

echo "Starting event generator (${SOAK_RATE} events/sec for ${SOAK_DURATION}s)..."
python3 "$SCRIPT_DIR/event_generator.py" \
    --rate "$SOAK_RATE" \
    --duration "$SOAK_DURATION" \
    --output "$SESSION_FILE" \
    > "$TMPDIR_BASE/gen.stdout" 2>&1 &
GEN_PID=$!
echo "Generator PID: $GEN_PID"

# Give the generator a moment to create the file before the forwarder starts.
sleep 1

# ─── Start forwarder ─────────────────────────────────────────────────────────

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

# Allow the forwarder to initialise before monitoring begins.
sleep 2

# ─── RSS monitoring loop ─────────────────────────────────────────────────────

echo ""
echo "RSS monitoring (${RSS_INTERVAL}s intervals for ${SOAK_DURATION}s)..."

# Write CSV header.
echo "timestamp_s,rss_kb" > "$RSS_LOG"

PEAK_RSS_KB=0
START_EPOCH=$(date +%s)
ELAPSED=0

while [[ $ELAPSED -lt $SOAK_DURATION ]]; do
    # Check forwarder is still alive.
    if ! kill -0 "$FWD_PID" 2>/dev/null; then
        echo "WARNING: Forwarder exited prematurely at t=${ELAPSED}s"
        break
    fi

    # Sample RSS (ps -o rss= returns KB on both macOS and Linux).
    CURRENT_RSS=$(ps -p "$FWD_PID" -o rss= 2>/dev/null || echo "0")
    CURRENT_RSS="${CURRENT_RSS//[[:space:]]/}"
    CURRENT_RSS="${CURRENT_RSS:-0}"

    if [[ "$CURRENT_RSS" -gt "$PEAK_RSS_KB" ]]; then
        PEAK_RSS_KB=$CURRENT_RSS
    fi

    PEAK_RSS_MB=$(( PEAK_RSS_KB / 1024 ))
    echo "${ELAPSED},${CURRENT_RSS}" >> "$RSS_LOG"

    echo "  [${ELAPSED}s] RSS=${CURRENT_RSS}KB peak=${PEAK_RSS_MB}MB"

    sleep "$RSS_INTERVAL"
    ELAPSED=$(( $(date +%s) - START_EPOCH ))
done

# ─── Wait for drain ───────────────────────────────────────────────────────────

echo ""
echo "Soak duration complete. Waiting ${DRAIN_SECONDS}s for forwarder to drain..."
sleep "$DRAIN_SECONDS"

# ─── Graceful forwarder shutdown ─────────────────────────────────────────────

echo "Stopping forwarder (SIGTERM)..."
if kill -0 "$FWD_PID" 2>/dev/null; then
    kill -TERM "$FWD_PID" 2>/dev/null || true
    sleep 3
    if kill -0 "$FWD_PID" 2>/dev/null; then
        echo "Forwarder still running — sending SIGKILL..."
        kill -KILL "$FWD_PID" 2>/dev/null || true
    fi
fi
wait "$FWD_PID" 2>/dev/null || true
FWD_PID=""  # prevent double-kill in cleanup

# ─── Stop event generator (if still running) ─────────────────────────────────

if kill -0 "$GEN_PID" 2>/dev/null; then
    echo "Stopping event generator..."
    kill -TERM "$GEN_PID" 2>/dev/null || true
    sleep 1
    kill -KILL "$GEN_PID" 2>/dev/null || true
fi
wait "$GEN_PID" 2>/dev/null || true
GEN_PID=""  # prevent double-kill in cleanup

echo ""
echo "Generator output:"
cat "$TMPDIR_BASE/gen.stdout" || true

# ─── Run post-soak analysis ──────────────────────────────────────────────────

EXPECTED_EVENTS=$(( SOAK_RATE * SOAK_DURATION ))
echo ""
echo "Running post-soak analysis (expected events: ${EXPECTED_EVENTS})..."

python3 "$SCRIPT_DIR/analyze_soak.py" \
    --rss-log "$RSS_LOG" \
    --events-file "$EVENTS_FILE" \
    --expected-events "$EXPECTED_EVENTS" \
    --max-rss-mb "$SOAK_MAX_RSS_MB" \
    --max-p99-latency-ms "$SOAK_MAX_P99_MS"

# analyze_soak.py exits 0 on PASS, 1 on FAIL.
