#!/usr/bin/env python3
# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
analyze_soak.py — Post-soak analysis: RSS monotonicity, p99 latency, event count.

Reads the RSS sample log and events sink output produced by soak_1hr.sh, then
prints a structured PASS/FAIL report and exits with a non-zero code if any
metric fails.

Usage:
    python3 analyze_soak.py \\
        --rss-log /tmp/soak_123/rss_log.csv \\
        --events-file /path/to/events.jsonl \\
        --expected-events 360000 \\
        --max-rss-mb 200 \\
        --max-p99-latency-ms 500

Exit codes:
    0 — all metrics PASS
    1 — one or more metrics FAIL
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# RSS analysis
# ---------------------------------------------------------------------------


def analyze_rss(rss_log_path: str, max_rss_mb: int) -> dict:
    """
    Read `timestamp_s,rss_kb` CSV rows, compute peak RSS (MB), and check
    monotonicity.

    Monotonicity rule: RSS at the end of the run should not exceed the RSS
    at the 5-minute mark by more than 50%. This allows initial allocation
    ramp-up while detecting unbounded growth over the rest of the run.
    """
    result = {
        "peak_rss_mb": None,
        "rss_at_5m_kb": None,
        "rss_at_end_kb": None,
        "monotonicity_ratio": None,
        "peak_pass": None,
        "monotonicity_pass": None,
        "error": None,
    }

    path = Path(rss_log_path)
    if not path.exists():
        result["error"] = f"RSS log not found: {rss_log_path}"
        result["peak_pass"] = False
        result["monotonicity_pass"] = False
        return result

    rows = []
    try:
        with open(rss_log_path, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    rows.append((float(row["timestamp_s"]), int(row["rss_kb"])))
                except (KeyError, ValueError):
                    continue
    except OSError as exc:
        result["error"] = str(exc)
        result["peak_pass"] = False
        result["monotonicity_pass"] = False
        return result

    if not rows:
        result["error"] = "RSS log is empty or has no valid rows"
        result["peak_pass"] = False
        result["monotonicity_pass"] = False
        return result

    peak_kb = max(rss_kb for _, rss_kb in rows)
    peak_mb = peak_kb / 1024.0
    result["peak_rss_mb"] = round(peak_mb, 2)
    result["peak_pass"] = peak_mb <= max_rss_mb

    # Monotonicity: compare RSS at t >= 300s (5 min) vs end.
    five_min_rows = [(t, rss) for t, rss in rows if t >= 300]
    if five_min_rows:
        rss_at_5m = five_min_rows[0][1]
        rss_at_end = rows[-1][1]
        result["rss_at_5m_kb"] = rss_at_5m
        result["rss_at_end_kb"] = rss_at_end
        if rss_at_5m > 0:
            ratio = rss_at_end / rss_at_5m
            result["monotonicity_ratio"] = round(ratio, 3)
            result["monotonicity_pass"] = ratio <= 1.5
        else:
            # RSS at 5 min is 0 — can't compute ratio; treat as PASS.
            result["monotonicity_ratio"] = 1.0
            result["monotonicity_pass"] = True
    else:
        # Run was shorter than 5 minutes — skip monotonicity check.
        result["monotonicity_ratio"] = None
        result["monotonicity_pass"] = True  # not applicable

    return result


# ---------------------------------------------------------------------------
# Event count + p99 latency analysis
# ---------------------------------------------------------------------------


def analyze_events(
    events_file_path: str,
    expected_events: int,
    max_p99_latency_ms: float,
) -> dict:
    """
    Count events in the sink output file and compute p99 latency.

    p99 latency is computed as the delta between event `timestamp` and
    `_sink_write_ts` when that field is present. If `_sink_write_ts` is
    absent, p99 latency is reported as N/A (not a failure).
    """
    result = {
        "actual_events": 0,
        "expected_events": expected_events,
        "loss_pct": None,
        "event_count_pass": None,
        "p99_latency_ms": None,
        "p99_pass": None,
        "p99_available": False,
        "error": None,
    }

    path = Path(events_file_path)
    if not path.exists():
        result["error"] = f"Events file not found: {events_file_path}"
        result["event_count_pass"] = False
        result["p99_pass"] = True  # not measurable; don't fail
        return result

    latencies_ms = []
    actual = 0

    try:
        with open(events_file_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                actual += 1
                try:
                    event = json.loads(line)
                    ts_event = event.get("timestamp")
                    ts_write = event.get("_sink_write_ts")
                    if ts_event and ts_write:
                        from datetime import datetime

                        def _parse(s: str):
                            # Handle both Z-suffix and +00:00 forms.
                            s = s.replace("Z", "+00:00")
                            return datetime.fromisoformat(s)

                        dt_event = _parse(ts_event)
                        dt_write = _parse(ts_write)
                        delta_ms = (dt_write - dt_event).total_seconds() * 1000.0
                        if delta_ms >= 0:
                            latencies_ms.append(delta_ms)
                except (json.JSONDecodeError, ValueError):
                    pass
    except OSError as exc:
        result["error"] = str(exc)
        result["event_count_pass"] = False
        result["p99_pass"] = True
        return result

    result["actual_events"] = actual

    if expected_events > 0:
        loss = max(0, expected_events - actual)
        result["loss_pct"] = round(loss / expected_events * 100.0, 4)
        # Allow up to 0.1% loss to account for graceful shutdown timing.
        result["event_count_pass"] = result["loss_pct"] <= 0.1
    else:
        result["loss_pct"] = 0.0
        result["event_count_pass"] = True

    if latencies_ms:
        result["p99_available"] = True
        latencies_ms.sort()
        idx = int(len(latencies_ms) * 0.99)
        p99 = latencies_ms[min(idx, len(latencies_ms) - 1)]
        result["p99_latency_ms"] = round(p99, 2)
        result["p99_pass"] = p99 <= max_p99_latency_ms
    else:
        result["p99_available"] = False
        result["p99_latency_ms"] = None
        result["p99_pass"] = True  # not measurable; treat as PASS

    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------


def print_report(rss: dict, events: dict, max_rss_mb: int, max_p99_ms: float) -> bool:
    """Print structured PASS/FAIL report. Returns True if all checks pass."""

    print("=" * 64)
    print("Soak Test Analysis Report")
    print("=" * 64)

    all_pass = True

    # --- RSS peak ---
    status = "PASS" if rss.get("peak_pass") else "FAIL"
    if not rss.get("peak_pass"):
        all_pass = False
    peak = rss.get("peak_rss_mb")
    peak_str = f"{peak} MB" if peak is not None else "N/A"
    print(f"\n[{status}] Peak RSS: {peak_str} (limit: {max_rss_mb} MB)")
    if rss.get("error"):
        print(f"       Error: {rss['error']}")

    # --- RSS monotonicity ---
    mono_pass = rss.get("monotonicity_pass")
    ratio = rss.get("monotonicity_ratio")
    if mono_pass is None or mono_pass:
        status = "PASS"
    else:
        status = "FAIL"
        all_pass = False
    ratio_str = f"{ratio:.3f}x" if ratio is not None else "N/A (run < 5 min)"
    print(f"[{status}] RSS Monotonicity: end/5min ratio = {ratio_str} (limit: 1.500x)")

    # --- Event count ---
    ec_pass = events.get("event_count_pass")
    status = "PASS" if ec_pass else "FAIL"
    if not ec_pass:
        all_pass = False
    actual = events.get("actual_events", 0)
    expected = events.get("expected_events", 0)
    loss_pct = events.get("loss_pct")
    loss_str = f"{loss_pct:.4f}%" if loss_pct is not None else "N/A"
    print(f"[{status}] Event Count: {actual}/{expected} events (loss: {loss_str}, limit: 0.1%)")
    if events.get("error"):
        print(f"       Error: {events['error']}")

    # --- p99 latency ---
    p99_pass = events.get("p99_pass")
    status = "PASS" if p99_pass else "FAIL"
    if not p99_pass:
        all_pass = False
    p99 = events.get("p99_latency_ms")
    p99_str = f"{p99} ms" if p99 is not None else "N/A (no _sink_write_ts)"
    print(f"[{status}] p99 Latency: {p99_str} (limit: {max_p99_ms} ms)")

    print("\n" + "=" * 64)
    verdict = "PASS" if all_pass else "FAIL"
    print(f"Overall verdict: {verdict}")
    print("=" * 64)

    return all_pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-soak analysis: RSS, monotonicity, event count, p99 latency")
    parser.add_argument("--rss-log", required=True, help="Path to RSS samples CSV")
    parser.add_argument("--events-file", required=True, help="Path to sink output JSONL")
    parser.add_argument("--expected-events", type=int, required=True, help="Expected event count")
    parser.add_argument("--max-rss-mb", type=int, default=200, help="Peak RSS limit in MB (default: 200)")
    parser.add_argument(
        "--max-p99-latency-ms",
        type=float,
        default=500.0,
        help="p99 latency limit in ms (default: 500)",
    )
    args = parser.parse_args()

    rss = analyze_rss(args.rss_log, args.max_rss_mb)
    events = analyze_events(args.events_file, args.expected_events, args.max_p99_latency_ms)

    all_pass = print_report(rss, events, args.max_rss_mb, args.max_p99_latency_ms)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
