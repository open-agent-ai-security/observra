"""Storage backend implementations."""

from observra.backends.jsonl import JSONLBackend
from observra.backends.multi import MultiBackend
from observra.backends.webhook import WebhookBackend

__all__ = ["JSONLBackend", "MultiBackend", "WebhookBackend"]

try:
    from observra.backends.otel import OTelExportBackend as OTelExportBackend

    __all__.append("OTelExportBackend")
except (ImportError, RuntimeError):
    pass

try:
    from observra.backends.otel_log import OTelLogBackend as OTelLogBackend

    __all__.append("OTelLogBackend")
except (ImportError, RuntimeError):
    pass
