"""Redaction patterns with semantic markers for sensitive data."""

import re
from enum import Enum
from functools import lru_cache


class RedactionMarker(Enum):
    """Semantic redaction markers by pattern type."""

    API_KEY = "[REDACTED:API_KEY]"
    BEARER_TOKEN = "[REDACTED:BEARER_TOKEN]"
    JWT = "[REDACTED:JWT]"
    PASSWORD = "[REDACTED:PASSWORD]"
    EMAIL = "[REDACTED:EMAIL]"
    IP_ADDRESS = "[REDACTED:IP]"
    AWS_KEY = "[REDACTED:AWS_KEY]"
    GENERIC = "[REDACTED]"


@lru_cache(maxsize=None)
def get_compiled_patterns() -> list[tuple[re.Pattern, RedactionMarker]]:
    """Return compiled regex patterns ordered from most specific to most general.

    Ordering prevents over-redaction: specific patterns (AWS keys, Bearer tokens)
    match before generic patterns (API keys, passwords).

    Returns:
        List of (compiled_regex, marker) tuples in descending specificity order
    """
    return [
        # 1. AWS Access Keys (very specific format)
        (re.compile(r'\b(AKIA[0-9A-Z]{16})\b'), RedactionMarker.AWS_KEY),

        # 2. Bearer tokens (RFC 6750 - contextual with "Bearer" keyword)
        (re.compile(r'\bBearer\s+([A-Za-z0-9\-._~+/]+=*)', re.IGNORECASE), RedactionMarker.BEARER_TOKEN),

        # 3. JWT tokens (3-part base64 structure)
        (re.compile(r'\b([A-Za-z0-9\-_]{20,})\.([A-Za-z0-9\-_]{3,})\.([A-Za-z0-9\-_]+)\b'), RedactionMarker.JWT),

        # 4. Generic API keys (contextual with keyword prefix to avoid ULIDs/hashes)
        (re.compile(
            r'\b(api[_-]?key|apikey|api[_-]?token|secret[_-]?key|access[_-]?token)'
            r'[\s:=]+[\'"]?([A-Za-z0-9\-_]{20,})[\'"]?', re.IGNORECASE
        ), RedactionMarker.API_KEY),

        # 5. Password assignments (contextual with keyword prefix)
        (re.compile(
            r'\b(password|passwd|pwd|pass)[\s:=]+[\'"]?([^\s\'"]{8,})[\'"]?', re.IGNORECASE
        ), RedactionMarker.PASSWORD),

        # 6. Email addresses (RFC 5322 simplified)
        (re.compile(r'\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b'), RedactionMarker.EMAIL),

        # 7. IPv4 addresses
        (re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b'), RedactionMarker.IP_ADDRESS),
    ]


def redact_string(text: str, custom_patterns: list[tuple[re.Pattern, str]] | None = None) -> str:
    """Apply redaction patterns to text, replacing matches with semantic markers.

    Args:
        text: String to redact
        custom_patterns: Optional list of (compiled_regex, marker_string) tuples

    Returns:
        Redacted string with semantic markers replacing sensitive data
    """
    if not isinstance(text, str):
        return text

    result = text

    # Apply built-in patterns
    for pattern, marker in get_compiled_patterns():
        result = pattern.sub(marker.value, result)

    # Apply custom patterns if provided
    if custom_patterns:
        for pattern, marker_string in custom_patterns:
            result = pattern.sub(marker_string, result)

    return result
