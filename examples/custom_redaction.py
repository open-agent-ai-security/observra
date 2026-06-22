"""Custom redaction patterns — add org-specific sensitive data patterns.

Usage:
    python examples/custom_redaction.py

Built-in patterns cover API keys, Bearer tokens, passwords, emails, and IPs.
This example shows how to add custom patterns for organization-specific secrets.
"""

from observra import initialize
from observra.core.context import initialize_trace
from observra.core.events import create_event

# Initialize with custom redaction patterns
initialize(
    backend="jsonl",
    path="redaction_demo.jsonl",
    custom_patterns=[
        (r"ACME_TOKEN_\w+", "ACME_TOKEN"),  # Internal tokens
        (r"proj_[a-z0-9]{20,}", "PROJECT_KEY"),  # Project keys
    ],
)

# Initialize trace context for event creation
initialize_trace()

# Create an event with sensitive data in kwargs (cold path = redacted)
event = create_event(
    event_type="model_error",  # cold path event
    error_message="Auth failed with ACME_TOKEN_abc123def456 for proj_abcdefghij1234567890",
)

print("Custom redaction demo:")
print(f"  Event type: {event.event_type}")
print(f"  Redacted data: {event.data}")
print()
print("Built-in redaction patterns:")
print("  - API keys:      api_key=sk_... -> [REDACTED:API_KEY]")
print("  - Bearer tokens: Bearer eyJ...  -> [REDACTED:BEARER_TOKEN]")
print("  - Passwords:     password=...   -> [REDACTED:PASSWORD]")
print("  - Emails:        user@host.com  -> [REDACTED:EMAIL]")
print("  - IP addresses:  192.168.1.1    -> [REDACTED:IP]")
print()
print("Hot path events (before_model, after_tool, etc.) strip ALL strings,")
print("keeping only numeric metrics. No redaction overhead needed.")
