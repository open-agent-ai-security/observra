# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Redactor class for recursive dict traversal with custom pattern support."""

import re
from typing import Any

from .metrics import _registry
from .patterns import redact_string
from .safe_regex import compile_safe_pattern


class Redactor:
    """Recursively redact sensitive data from dictionaries with custom pattern support.

    The Redactor applies both built-in patterns (from patterns.py) and optional
    custom patterns to strings, while recursively traversing nested dicts and lists.
    Non-string values (int, float, bool, None, Decimal) pass through unchanged.

    Custom patterns are compiled using compile_safe_pattern() to prevent ReDoS
    (SEC-05, SEC-06). Unsafe patterns (catastrophic backtracking, excessive length)
    raise SafeRegexError at construction time rather than hanging at match time.
    """

    def __init__(self, custom_patterns: list[tuple[str, str]] | None = None):
        """Initialize Redactor with optional custom patterns.

        Args:
            custom_patterns: Optional list of (regex_pattern_string, marker_name) tuples.
                            Each pattern is compiled using compile_safe_pattern() and used
                            with marker f"[REDACTED:{marker_name}]".

        Raises:
            SafeRegexError: If any custom pattern is unsafe (too long, has catastrophic
                           backtracking, times out during compilation, or is syntactically
                           invalid). This is raised at construction time, not at match time.
        """
        self._custom_patterns: list[tuple[re.Pattern, str]] = []

        if custom_patterns:
            for pattern_str, marker_name in custom_patterns:
                compiled = compile_safe_pattern(pattern_str)
                marker_string = f"[REDACTED:{marker_name}]"
                self._custom_patterns.append((compiled, marker_string))

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact all string values in a dictionary.

        Returns a NEW dict (immutable operation, preserves original).

        Args:
            data: Dictionary to redact

        Returns:
            New dictionary with redacted values
        """
        return {key: self._redact_value(value) for key, value in data.items()}

    def _redact_value(self, value: Any) -> Any:
        """Dispatch redaction by value type.

        Args:
            value: Value to potentially redact

        Returns:
            Redacted value (or original if non-string)
        """
        if isinstance(value, str):
            return self._redact_string(value)
        elif isinstance(value, dict):
            return self.redact_dict(value)
        elif isinstance(value, list):
            return [self._redact_value(item) for item in value]
        else:
            # Pass through: int, float, bool, None, Decimal, etc.
            return value

    def _redact_string(self, text: str) -> str:
        """Apply built-in and custom patterns to a string.

        Args:
            text: String to redact

        Returns:
            Redacted string with semantic markers
        """
        # Apply built-in patterns first
        result = redact_string(text)

        # Then apply custom patterns
        for pattern, marker_string in self._custom_patterns:
            result = pattern.sub(marker_string, result)

        # Increment per-string counter when redaction was actually applied (OBS-01).
        # One increment per string that changed, regardless of how many patterns matched.
        if result != text:
            _registry.inc_counter("observra_redaction_applied_total")

        return result
