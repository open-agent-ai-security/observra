# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Profile GIL contention with and without ProcessPoolExecutor offload.

Run with py-spy:
    sudo py-spy record --gil --subprocesses -o profile_direct.svg -- python3 tests/integration/profile_gil.py direct
    sudo py-spy record --gil --subprocesses -o profile_pooled.svg -- python3 tests/integration/profile_gil.py pooled

Or without py-spy (prints timing comparison):
    python3 tests/integration/profile_gil.py compare
"""

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import tempfile

from observra.backends.jsonl import JSONLBackend
from observra.core.events import TelemetryEvent, create_event
from observra.core.pool_writer import PooledWriter
from observra.core.queue import DropOldestQueue
from observra.core.worker import BackgroundWorker


def make_events(n: int) -> list[TelemetryEvent]:
    """Generate n test events."""
    events = []
    for i in range(n):
        e = create_event(
            event_type="after_model",
            agent_name=f"test-agent-{i % 10}",
            framework="test",
        )
        events.append(e)
    return events


def run_direct(events: list[TelemetryEvent], output_dir: str):
    """Write events directly through BackgroundWorker (no pool)."""
    backend = JSONLBackend(os.path.join(output_dir, "direct.jsonl"))
    q = DropOldestQueue(maxsize=20000)
    worker = BackgroundWorker(q, backend)

    start = time.monotonic()
    for e in events:
        q.put_nowait(e)
    # Wait for drain
    while q.qsize() > 0:
        time.sleep(0.01)
    elapsed = time.monotonic() - start

    worker._shutdown()
    backend.close()
    return elapsed


def run_pooled(events: list[TelemetryEvent], output_dir: str):
    """Write events through PooledWriter (ProcessPoolExecutor offload)."""
    pooled = PooledWriter(
        backend_type="jsonl",
        backend_kwargs={"path": os.path.join(output_dir, "pooled.jsonl")},
        max_workers=4,
    )
    q = DropOldestQueue(maxsize=20000)
    worker = BackgroundWorker(q, pooled)

    start = time.monotonic()
    for e in events:
        q.put_nowait(e)
    # Wait for drain
    while q.qsize() > 0:
        time.sleep(0.01)
    elapsed = time.monotonic() - start

    worker._shutdown()
    pooled.close()
    return elapsed


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"
    n_events = 5000

    print(f"Generating {n_events} events...")
    events = make_events(n_events)

    with tempfile.TemporaryDirectory() as tmpdir:
        if mode == "direct":
            print("Running DIRECT path (no pool, GIL held during writes)...")
            elapsed = run_direct(events, tmpdir)
            print(f"Direct: {elapsed:.3f}s for {n_events} events ({n_events / elapsed:.0f} events/s)")

        elif mode == "pooled":
            print("Running POOLED path (ProcessPoolExecutor, GIL released)...")
            elapsed = run_pooled(events, tmpdir)
            print(f"Pooled: {elapsed:.3f}s for {n_events} events ({n_events / elapsed:.0f} events/s)")

        elif mode == "compare":
            print("--- Direct path (GIL held) ---")
            t_direct = run_direct(events, tmpdir)
            print(f"Direct: {t_direct:.3f}s ({n_events / t_direct:.0f} events/s)")

            print("\n--- Pooled path (GIL released) ---")
            t_pooled = run_pooled(events, tmpdir)
            print(f"Pooled: {t_pooled:.3f}s ({n_events / t_pooled:.0f} events/s)")

            print("\n--- Summary ---")
            print(f"Direct: {t_direct:.3f}s")
            print(f"Pooled: {t_pooled:.3f}s")
            if t_direct > 0:
                ratio = t_direct / t_pooled if t_pooled > 0 else float("inf")
                print(f"Speedup: {ratio:.2f}x")
            print("\nGIL analysis: ProcessPoolExecutor uses separate processes.")
            print("By definition, child processes have their own GIL.")
            print("The main thread's GIL is NOT held during subprocess I/O.")
        else:
            print(f"Unknown mode: {mode}")
            print("Usage: python3 profile_gil.py [direct|pooled|compare]")
            sys.exit(1)


if __name__ == "__main__":
    main()
