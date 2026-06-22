"""Logging bridge — capture stdlib logging calls as telemetry events.

Usage:
    python examples/logging_bridge.py

The TelemetryLoggingHandler bridges Python's standard logging module into
the telemetry system. Any log message emitted through a logger with this
handler attached becomes a telemetry event with type 'log_message'.
"""

import logging

from observra import create_logging_handler, initialize
from observra.core.context import initialize_trace

# Initialize telemetry
initialize(
    backend="jsonl",
    path="logging_bridge.jsonl",
)
# Initialize trace context (normally done by plugin's before_run_callback)
initialize_trace()

# Create a logging handler connected to the telemetry queue
handler = create_logging_handler(level=logging.WARNING)

# Attach to any logger
app_logger = logging.getLogger("myapp.auth")
app_logger.addHandler(handler)
app_logger.setLevel(logging.DEBUG)

# Also add a console handler to see output
console = logging.StreamHandler()
console.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
app_logger.addHandler(console)

print("Logging bridge demo:")
print("  Handler level: WARNING (only WARNING+ become telemetry events)")
print("  Logger level: DEBUG (all messages shown on console)")
print()

# These go to console only (below handler threshold)
app_logger.debug("Debug: checking credentials")
app_logger.info("Info: user login attempt")

# These go to BOTH console AND telemetry
app_logger.warning("Warning: 3 failed login attempts from 10.0.0.1")
app_logger.error("Error: account locked after 5 failures")

print()
print("Result: 2 telemetry events created (warning + error)")
print("Log messages are classified as cold path -> PII redacted before storage")
print("  '10.0.0.1' in the warning would be redacted to [REDACTED:IP]")
