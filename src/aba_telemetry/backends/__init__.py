"""Storage backend implementations."""

from aba_telemetry.backends.jsonl import JSONLBackend
from aba_telemetry.backends.multi import MultiBackend
from aba_telemetry.backends.webhook import WebhookBackend

__all__ = ['JSONLBackend', 'MultiBackend', 'WebhookBackend']

try:
    from aba_telemetry.backends.otel import OTelExportBackend
    __all__.append('OTelExportBackend')
except (ImportError, RuntimeError):
    pass

try:
    from aba_telemetry.backends.otel_log import OTelLogBackend
    __all__.append('OTelLogBackend')
except (ImportError, RuntimeError):
    pass
