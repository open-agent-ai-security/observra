#!/usr/bin/env python3
"""
event_generator.py — Sustained synthetic event generator for soak tests.

Writes Claude session assistant JSONL events at a configurable rate for a
configurable duration. Used by tests/load/soak_1hr.sh (Phase 34, TEST-01).

Usage:
    python3 event_generator.py --rate 100 --duration 3600 --output /tmp/events.jsonl

Exit codes:
    0 — completed successfully
    1 — error (I/O failure, invalid arguments)
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone


def generate_events(rate: float, duration: float, output_path: str) -> None:
    """
    Write synthetic Claude session assistant events at `rate` events/sec
    for `duration` seconds to `output_path` (JSONL, one event per line).

    Rate limiting uses time.monotonic() to compensate for any drift.
    Progress is printed every 60 seconds to stdout.
    """
    interval = 1.0 / rate
    start_mono = time.monotonic()
    deadline = start_mono + duration
    next_report = start_mono + 60.0

    count = 0
    last_report_count = 0
    last_report_time = start_mono

    with open(output_path, "w", buffering=1) as fh:
        counter = 0
        while True:
            now = time.monotonic()
            if now >= deadline:
                break

            event = {
                "type": "assistant",
                "message": {
                    "id": f"msg_{counter:08d}",
                    "model": "claude-opus-4-5",
                    "content": [{"type": "text", "text": f"Response {counter}"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
                "sessionId": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            fh.write(json.dumps(event) + "\n")
            fh.flush()

            counter += 1
            count += 1

            # Progress report every 60 seconds.
            if now >= next_report:
                elapsed = now - start_mono
                interval_events = count - last_report_count
                interval_time = now - last_report_time
                actual_rate = interval_events / interval_time if interval_time > 0 else 0.0
                print(
                    f"[{elapsed:.0f}s] Wrote {count} events ({actual_rate:.1f}/s actual)",
                    flush=True,
                )
                next_report = now + 60.0
                last_report_count = count
                last_report_time = now

            # Rate-limit: sleep until the next event slot.
            next_event_time = start_mono + (count * interval)
            sleep_time = next_event_time - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)

    elapsed_total = time.monotonic() - start_mono
    print(
        f"Generator complete: {count} events in {elapsed_total:.1f}s",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sustained synthetic event generator for soak tests")
    parser.add_argument(
        "--rate",
        type=float,
        default=100.0,
        help="Events per second (default: 100)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3600.0,
        help="Duration in seconds (default: 3600)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSONL file path",
    )
    args = parser.parse_args()

    if args.rate <= 0:
        print("ERROR: --rate must be positive", file=sys.stderr)
        sys.exit(1)
    if args.duration <= 0:
        print("ERROR: --duration must be positive", file=sys.stderr)
        sys.exit(1)

    print(
        f"Starting generator: rate={args.rate}/s duration={args.duration}s output={args.output}",
        flush=True,
    )
    generate_events(rate=args.rate, duration=args.duration, output_path=args.output)


if __name__ == "__main__":
    main()
