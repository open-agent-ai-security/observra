#!/usr/bin/env bash
# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
# uat-01-concurrent-installer.sh — UAT-01: Concurrent installer race test.
#
# Purpose: Validate that three simultaneous forwarder instances launched from
# distinct project directories do NOT collide on port allocation. Confirms
# PortRegistry atomic save produces three non-overlapping port triplets and no
# process exits with SYSEXIT_PORTS_UNAVAILABLE (exit code 3).
#
# Platform: macOS (bash 3.2 compatible — no associative arrays, no wait -n,
#           no mapfile, no ${var,,})
#
# Prerequisite: cd rust && cargo build --release
#
# Usage:
#   tests/uat/uat-01-concurrent-installer.sh
#
# Exit codes:
#   0 — all checks PASS
#   1 — one or more checks FAIL, or setup error

echo "================================================================"
echo "Phase 41 — UAT-01: Concurrent Installer Race Test"
echo "Validates port allocation atomicity across 3 concurrent forwarder"
echo "instances. Intended platform: macOS."
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

# ─── Temp directory + PID variables + cleanup trap ───────────────────────────

TMPDIR_BASE=$(mktemp -d)
PID1=""
PID2=""
PID3=""

cleanup() {
    echo ""
    echo "Cleaning up..."
    if [[ -n "$PID1" ]] && kill -0 "$PID1" 2>/dev/null; then
        kill -TERM "$PID1" 2>/dev/null || true
        sleep 1
        kill -KILL "$PID1" 2>/dev/null || true
    fi
    if [[ -n "$PID2" ]] && kill -0 "$PID2" 2>/dev/null; then
        kill -TERM "$PID2" 2>/dev/null || true
        sleep 1
        kill -KILL "$PID2" 2>/dev/null || true
    fi
    if [[ -n "$PID3" ]] && kill -0 "$PID3" 2>/dev/null; then
        kill -TERM "$PID3" 2>/dev/null || true
        sleep 1
        kill -KILL "$PID3" 2>/dev/null || true
    fi
    wait "$PID1" 2>/dev/null || true
    wait "$PID2" 2>/dev/null || true
    wait "$PID3" 2>/dev/null || true
    rm -rf "$TMPDIR_BASE"
}
trap cleanup EXIT

# ─── Create 3 distinct project directories ───────────────────────────────────

mkdir -p "$TMPDIR_BASE/proj1" "$TMPDIR_BASE/proj2" "$TMPDIR_BASE/proj3"

echo "Launching 3 concurrent forwarder instances..."
echo "  HOME=$TMPDIR_BASE (shared ports.json registry)"
echo "  Project dirs: proj1, proj2, proj3"
echo ""

# ─── Launch 3 concurrent forwarder instances ─────────────────────────────────

HOME="$TMPDIR_BASE" USERPROFILE="$TMPDIR_BASE" \
    "$BINARY" --project-dir "$TMPDIR_BASE/proj1" run \
    > "$TMPDIR_BASE/fwd1.stdout" 2> "$TMPDIR_BASE/fwd1.stderr" &
PID1=$!

HOME="$TMPDIR_BASE" USERPROFILE="$TMPDIR_BASE" \
    "$BINARY" --project-dir "$TMPDIR_BASE/proj2" run \
    > "$TMPDIR_BASE/fwd2.stdout" 2> "$TMPDIR_BASE/fwd2.stderr" &
PID2=$!

HOME="$TMPDIR_BASE" USERPROFILE="$TMPDIR_BASE" \
    "$BINARY" --project-dir "$TMPDIR_BASE/proj3" run \
    > "$TMPDIR_BASE/fwd3.stdout" 2> "$TMPDIR_BASE/fwd3.stderr" &
PID3=$!

echo "Forwarder PIDs: PID1=$PID1 PID2=$PID2 PID3=$PID3"
echo "Waiting 10s for port allocation to complete..."
sleep 10

# Kill all three — we only care about port allocation, not sustained runtime
if [[ -n "$PID1" ]] && kill -0 "$PID1" 2>/dev/null; then
    kill -TERM "$PID1" 2>/dev/null || true
fi
if [[ -n "$PID2" ]] && kill -0 "$PID2" 2>/dev/null; then
    kill -TERM "$PID2" 2>/dev/null || true
fi
if [[ -n "$PID3" ]] && kill -0 "$PID3" 2>/dev/null; then
    kill -TERM "$PID3" 2>/dev/null || true
fi

# Collect exit codes — macOS bash 3.2: individual wait calls (no wait -n)
EXIT1=0
EXIT2=0
EXIT3=0
wait "$PID1" || EXIT1=$?
wait "$PID2" || EXIT2=$?
wait "$PID3" || EXIT3=$?

# Clear PIDs to avoid double-kill in cleanup
PID1=""
PID2=""
PID3=""

echo "Exit codes: EXIT1=$EXIT1 EXIT2=$EXIT2 EXIT3=$EXIT3"
echo ""

# ─── FAIL accumulator ────────────────────────────────────────────────────────

FAIL=0

# ─── CHECK A: No SYSEXIT_PORTS_UNAVAILABLE (exit code 3) ────────────────────

echo "--- CHECK A: SYSEXIT_PORTS_UNAVAILABLE (exit code 3) ---"
# SYSEXIT_PORTS_UNAVAILABLE = 3 (rust/src/main.rs)
if [[ "$EXIT1" -eq 3 ]] || [[ "$EXIT2" -eq 3 ]] || [[ "$EXIT3" -eq 3 ]]; then
    echo "CHECK A [FAIL]: One or more processes exited with SYSEXIT_PORTS_UNAVAILABLE (3)"
    echo "  EXIT1=$EXIT1 EXIT2=$EXIT2 EXIT3=$EXIT3"
    FAIL=1
else
    echo "CHECK A [PASS]: No process exited with exit code 3 (ports_unavailable)"
    echo "  EXIT1=$EXIT1 EXIT2=$EXIT2 EXIT3=$EXIT3"
fi
echo ""

# ─── CHECK B: ports.json has 3 entries with no duplicate ports ───────────────

echo "--- CHECK B: ports.json uniqueness ---"
# ports.json path: $HOME/.config/agent-telemetry/ports.json
PORTS_JSON="$TMPDIR_BASE/.config/agent-telemetry/ports.json"

if [[ ! -f "$PORTS_JSON" ]]; then
    echo "CHECK B [FAIL]: ports.json not found at $PORTS_JSON"
    echo "  (Forwarder may have exited before writing registry)"
    FAIL=1
else
    # Use python3 for JSON parsing — do not hand-roll JSON parsing with grep/sed
    CHECK_B_RESULT=0
    python3 - "$PORTS_JSON" <<'PYEOF' || CHECK_B_RESULT=$?
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        registry = json.load(f)
except Exception as e:
    print(f"CHECK B [FAIL]: Could not parse ports.json: {e}")
    sys.exit(1)

entries = list(registry.get("entries", registry).values())
all_ports = []
for entry in entries:
    all_ports.extend(entry.get("ports", []))

if len(entries) < 3:
    print(f"CHECK B [FAIL]: Expected >= 3 entries in registry, got {len(entries)}")
    sys.exit(1)

if len(all_ports) != len(set(all_ports)):
    dupes = [p for p in all_ports if all_ports.count(p) > 1]
    print(f"CHECK B [FAIL]: Duplicate ports detected in ports.json: {sorted(set(dupes))}")
    sys.exit(1)

print(f"CHECK B [PASS]: {len(entries)} entries, {len(all_ports)} ports, all unique")
PYEOF
    if [[ "$CHECK_B_RESULT" -ne 0 ]]; then
        FAIL=1
    fi
fi
echo ""

# ─── Final verdict ────────────────────────────────────────────────────────────

if [[ "$FAIL" -eq 0 ]]; then
    echo "UAT-01 [PASS]: Concurrent installer race — all checks passed"
    exit 0
else
    echo "UAT-01 [FAIL]: One or more checks failed — see above"
    exit 1
fi
