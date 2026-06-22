"""Safe regex compilation with ReDoS prevention.

This module provides compile_safe_pattern(), which enforces:
1. Pattern length limit (default 1024 characters, per SEC-06)
2. RE2 compilation preference (linear-time, no backtracking), per SEC-05
3. Fallback to stdlib re with compile-time timeout + structural canary check (100ms)
   when google-re2 is not installed

Usage:
    from observra.core.safe_regex import compile_safe_pattern, SafeRegexError

    try:
        pattern = compile_safe_pattern(user_provided_regex)
    except SafeRegexError as e:
        print(f"Rejected: {e.reason}")
"""

import queue
import re
import threading
from typing import Union

# Try to import google-re2. If not available, we fall back to stdlib re.
try:
    import re2 as _re2_module  # type: ignore[import-not-found]

    _RE2_AVAILABLE = True
except ImportError:
    _re2_module = None  # type: ignore[assignment]
    _RE2_AVAILABLE = False

# ── Constants ──────────────────────────────────────────────────────────────────

#: Maximum allowed pattern length in characters (SEC-06).
MAX_PATTERN_LENGTH: int = 1024

#: Compilation timeout in milliseconds (SEC-06).
COMPILE_TIMEOUT_MS: int = 100

#: Canary search timeout in milliseconds — used by the stdlib re fallback.
_CANARY_TIMEOUT_MS: int = 50

# ── Structural ReDoS detection patterns ───────────────────────────────────────
# These identify common catastrophic backtracking structures in regex patterns.
# This is a conservative set targeting the most dangerous known patterns.
#
# Detection rationale:
# - Nested quantifiers: (X+)+ or (X*)+ or (X+)* create exponential paths
# - Quantified alternation with overlap: (a|a)+ etc.
# - The re module holds the GIL during search, so thread-based timeouts are
#   unreliable for detecting runtime ReDoS. Structural analysis is used instead
#   for the re fallback path.
_REDOS_STRUCTURAL_PATTERNS: list[re.Pattern] = [
    # Nested quantifiers: (.+)+, (.+)*, (.*)+, (.*)*, ([...]+)+, etc.
    # Match: open paren, any content including +/* quantifier, close paren, then +/*
    re.compile(r"\([^)]*[+*][^)]*\)[+*]"),
    # Alternation inside repeated group sharing a prefix, e.g. (a+|a)+
    re.compile(r"\([^)]*\|[^)]*\)[+*]"),
]


# ── Exception ─────────────────────────────────────────────────────────────────


class SafeRegexError(ValueError):
    """Raised when a user-provided regex pattern is rejected for safety reasons.

    Attributes:
        reason: A human-readable string describing why the pattern was rejected.
                One of the following prefixes:
                - "exceeds maximum length of {limit} characters (got {actual})"
                - "pattern uses backtracking constructs not supported by RE2: ..."
                - "pattern has catastrophic backtracking structure: ..."
                - "compilation timed out (>{timeout}ms)"
                - "invalid regex: ..."
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ── Core function ──────────────────────────────────────────────────────────────


def compile_safe_pattern(
    pattern_str: str,
    max_length: int = MAX_PATTERN_LENGTH,
) -> "Union[re.Pattern, re2.Pattern]":  # type: ignore[name-defined]  # noqa: F821
    """Compile a user-provided regex pattern with safety guardrails.

    Enforces:
    - Length limit: patterns longer than max_length are rejected immediately.
    - RE2 compilation (preferred): Google RE2 rejects patterns with catastrophic
      backtracking constructs (backreferences, possessive quantifiers, lookaheads
      with unlimited repetition) at compile time.
    - re fallback with structural analysis: if google-re2 is not installed, uses
      stdlib re with a 100ms compile timeout and structural pattern analysis to
      detect common ReDoS constructs (nested quantifiers, etc.).

    Args:
        pattern_str: The regex pattern string to compile.
        max_length: Maximum allowed pattern length. Defaults to MAX_PATTERN_LENGTH (1024).

    Returns:
        A compiled re2.Pattern if google-re2 is installed, else a re.Pattern.

    Raises:
        SafeRegexError: If the pattern exceeds max_length, uses backtracking
                        constructs, times out during compilation, or is syntactically invalid.
    """
    # ── 1. Length check (fast, no imports needed) ──────────────────────────
    if len(pattern_str) > max_length:
        reason = (
            f"exceeds maximum length of {max_length} characters "
            f"(got {len(pattern_str)}). "
            f"Consider simplifying the pattern or using a non-backtracking construct."
        )
        raise SafeRegexError(reason)

    # ── 2. RE2 path (preferred — linear-time, no backtracking) ────────────
    if _RE2_AVAILABLE:
        return _compile_with_re2(pattern_str)

    # ── 3. stdlib re fallback with timeout + structural canary ────────────
    return _compile_with_re_fallback(pattern_str)


def _compile_with_re2(pattern_str: str) -> "re2.Pattern":  # type: ignore[name-defined]  # noqa: F821
    """Compile using google-re2. RE2 natively rejects backtracking patterns."""
    try:
        return _re2_module.compile(pattern_str)
    except Exception as exc:
        # re2 raises re2.error (subclass of Exception) for invalid or
        # backtracking patterns.
        detail = str(exc)
        reason = (
            f"pattern uses backtracking constructs not supported by RE2: {detail}. "
            f"Consider simplifying the pattern or using a non-backtracking construct."
        )
        raise SafeRegexError(reason) from exc


def _check_structural_redos(pattern_str: str) -> None:
    """Check for common catastrophic backtracking structures in a pattern string.

    This is a conservative structural analysis using known ReDoS signatures.
    It runs BEFORE compilation, so it cannot catch all possible ReDoS patterns,
    but it reliably catches the most dangerous common cases.

    Args:
        pattern_str: The raw pattern string to analyze.

    Raises:
        SafeRegexError: If a known catastrophic backtracking structure is found.
    """
    for detector in _REDOS_STRUCTURAL_PATTERNS:
        match = detector.search(pattern_str)
        if match:
            reason = (
                f"pattern has catastrophic backtracking structure "
                f"(detected nested quantifiers or overlapping alternation near "
                f"'{match.group(0)}'). "
                f"Consider simplifying the pattern or using a non-backtracking construct."
            )
            raise SafeRegexError(reason)


def _compile_with_re_fallback(pattern_str: str) -> re.Pattern:
    """Compile using stdlib re with structural canary check and compile-time timeout.

    Note: the Python re module holds the GIL during search, which means thread-based
    runtime timeout for the search itself is unreliable. We use structural analysis
    to detect common ReDoS patterns instead.
    """
    # ── Structural canary check (before compilation) ───────────────────────
    # Detect common catastrophic backtracking patterns by structure.
    # This is done BEFORE compilation to fail fast.
    _check_structural_redos(pattern_str)

    # ── Compile with timeout ──────────────────────────────────────────────
    # re.compile() itself is fast for most patterns, but can be slow for
    # very complex or deeply nested patterns.
    compile_result: queue.Queue = queue.Queue(maxsize=1)
    compile_exception: queue.Queue = queue.Queue(maxsize=1)

    def _do_compile() -> None:
        try:
            compiled = re.compile(pattern_str)
            compile_result.put(compiled)
        except re.error as e:
            compile_exception.put(e)
        except Exception as e:
            compile_exception.put(e)

    compile_thread = threading.Thread(target=_do_compile, daemon=True)
    compile_thread.start()
    compile_thread.join(timeout=COMPILE_TIMEOUT_MS / 1000.0)

    if compile_thread.is_alive():
        # Compilation did not complete within the timeout window.
        reason = (
            f"compilation timed out (>{COMPILE_TIMEOUT_MS}ms). "
            f"The pattern may be too complex. "
            f"Consider simplifying the pattern or using a non-backtracking construct."
        )
        raise SafeRegexError(reason)

    # Check for compilation errors
    if not compile_exception.empty():
        exc = compile_exception.get_nowait()
        reason = f"invalid regex: {exc}. Consider simplifying the pattern or using a non-backtracking construct."
        raise SafeRegexError(reason)

    compiled_pattern: re.Pattern = compile_result.get_nowait()
    return compiled_pattern
