"""Tests for safe_regex module — ReDoS prevention for user-provided patterns.

These tests verify:
 1. Safe patterns compile successfully
 2. Catastrophic backtracking patterns are rejected (via RE2 or canary check)
 3. Patterns exceeding max length are rejected
 4. Custom max_length override works
 5. Redactor raises SafeRegexError on construction for unsafe patterns
 6. Redactor operates normally for safe patterns
 7. Return type is re2.Pattern when re2 is installed, re.Pattern otherwise
 8. Error messages include specific reason and suggest simplification
"""

import re

import pytest

from aba_telemetry.core.safe_regex import (
    MAX_PATTERN_LENGTH,
    SafeRegexError,
    compile_safe_pattern,
)
from aba_telemetry.core.redaction import Redactor


# ── Test 1: valid pattern compiles and returns a compiled pattern ──────────────


def test_valid_pattern_compiles():
    """A simple safe pattern should compile without error."""
    result = compile_safe_pattern(r"\b\d{3}\b")
    # Should be able to use .search() like any compiled pattern
    assert result.search("abc 123 def") is not None
    assert result.search("no digits") is None


# ── Test 2: catastrophic backtracking pattern is rejected ──────────────────────


def test_catastrophic_backtracking_rejected():
    """(a+)+$ is the canonical ReDoS pattern — must be rejected with clear reason."""
    with pytest.raises(SafeRegexError) as exc_info:
        compile_safe_pattern("(a+)+$")
    msg = str(exc_info.value)
    # Either RE2 rejects it as a backtracking pattern, or the re fallback catches it
    assert (
        "backtracking" in msg.lower()
        or "timeout" in msg.lower()
        or "timed out" in msg.lower()
    ), f"Expected backtracking/timeout message, got: {msg}"


# ── Test 3: pattern exceeding 1024 chars is rejected with length error ─────────


def test_pattern_too_long_default_limit():
    """Patterns exceeding MAX_PATTERN_LENGTH (1024) are rejected before compilation."""
    long_pattern = "x" * (MAX_PATTERN_LENGTH + 1)
    with pytest.raises(SafeRegexError) as exc_info:
        compile_safe_pattern(long_pattern)
    msg = str(exc_info.value)
    assert "exceeds maximum length" in msg.lower() or "too long" in msg.lower(), (
        f"Expected length error, got: {msg}"
    )
    # Should mention the actual length or limit
    assert str(MAX_PATTERN_LENGTH) in msg or str(MAX_PATTERN_LENGTH + 1) in msg, (
        f"Expected length details in message, got: {msg}"
    )


# ── Test 4: custom max_length override ────────────────────────────────────────


def test_custom_max_length_rejects_pattern():
    """compile_safe_pattern(pattern, max_length=50) rejects a 51-char pattern."""
    slightly_too_long = "x" * 51
    with pytest.raises(SafeRegexError) as exc_info:
        compile_safe_pattern(slightly_too_long, max_length=50)
    msg = str(exc_info.value)
    assert "exceeds maximum length" in msg.lower() or "too long" in msg.lower(), (
        f"Expected length error, got: {msg}"
    )


def test_custom_max_length_accepts_at_boundary():
    """compile_safe_pattern with max_length=50 accepts exactly a 50-char safe pattern."""
    exactly_50 = "a" * 50
    # Should not raise
    result = compile_safe_pattern(exactly_50, max_length=50)
    assert result is not None


# ── Test 5: Redactor raises SafeRegexError at construction for unsafe pattern ─


def test_redactor_rejects_backtracking_pattern_at_construction():
    """Redactor([('(a+)+$', 'BAD')]) raises SafeRegexError at __init__ time."""
    with pytest.raises(SafeRegexError):
        Redactor([("(a+)+$", "BAD")])


# ── Test 6: Redactor operates normally with safe patterns ─────────────────────


def test_redactor_accepts_safe_pattern_and_redacts():
    """Redactor with a safe pattern should successfully redact matching text."""
    redactor = Redactor([(r"\bsecret\b", "SECRET")])
    result = redactor._redact_string("this is secret info")
    assert "[REDACTED:SECRET]" in result, f"Expected redaction, got: {result}"
    # Non-matching text passes through
    normal = redactor._redact_string("nothing to redact")
    assert "[REDACTED" not in normal


# ── Test 7: return type is re2.Pattern when re2 installed, re.Pattern otherwise ─


def test_return_type_is_correct():
    """The return type should be re2.Pattern if re2 is available, re.Pattern otherwise."""
    try:
        import re2

        _re2_available = True
    except ImportError:
        _re2_available = False

    result = compile_safe_pattern(r"\d+")
    if _re2_available:
        assert isinstance(result, re2.Pattern), (
            f"Expected re2.Pattern when re2 is installed, got {type(result)}"
        )
    else:
        assert isinstance(result, re.Pattern), (
            f"Expected re.Pattern when re2 is absent, got {type(result)}"
        )


# ── Test 8: error messages include specific reason and suggest simplification ──


def test_error_message_includes_reason_and_suggestion_for_length():
    """SafeRegexError from length check includes specific reason and simplification hint."""
    with pytest.raises(SafeRegexError) as exc_info:
        compile_safe_pattern("x" * (MAX_PATTERN_LENGTH + 1))
    msg = str(exc_info.value)
    assert "simplif" in msg.lower() or "consider" in msg.lower(), (
        f"Expected suggestion to simplify, got: {msg}"
    )


def test_error_message_includes_reason_and_suggestion_for_backtracking():
    """SafeRegexError from backtracking check includes specific reason and simplification hint."""
    with pytest.raises(SafeRegexError) as exc_info:
        compile_safe_pattern("(a+)+$")
    msg = str(exc_info.value)
    assert "simplif" in msg.lower() or "consider" in msg.lower(), (
        f"Expected suggestion to simplify, got: {msg}"
    )


# ── Additional: error includes SafeRegexError.reason field ──────────────────


def test_safe_regex_error_has_reason_attribute():
    """SafeRegexError should have a 'reason' attribute with a specific reason string."""
    with pytest.raises(SafeRegexError) as exc_info:
        compile_safe_pattern("x" * (MAX_PATTERN_LENGTH + 1))
    error = exc_info.value
    assert hasattr(error, "reason"), "SafeRegexError should have a 'reason' attribute"
    assert error.reason, "reason should be non-empty"
