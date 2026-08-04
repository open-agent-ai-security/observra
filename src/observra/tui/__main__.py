# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Entry point for `python -m observra.tui`."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="observra-watch",
        description="Live terminal dashboard for Observra telemetry",
    )
    parser.add_argument(
        "--db",
        default="telemetry.db",
        help="Path to SQLite telemetry database (default: telemetry.db)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds (default: 0.5)",
    )
    args = parser.parse_args()

    try:
        from observra.tui.app import ObservraWatch
    except ImportError:
        print(
            "ERROR: Textual is required for the TUI. Install with:\n  pip install observra[tui]",
            file=sys.stderr,
        )
        sys.exit(1)

    app = ObservraWatch(db_path=args.db, poll_interval=args.poll_interval)
    app.run()


if __name__ == "__main__":
    main()
