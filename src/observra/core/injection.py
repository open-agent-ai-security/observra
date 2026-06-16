"""Prompt injection pattern detection for security analysis."""

import logging
import re
from enum import Enum
from functools import lru_cache

logger = logging.getLogger(__name__)


class InjectionMarker(Enum):
    """Prompt injection pattern types."""

    JAILBREAK_DAN = "JAILBREAK_DAN"
    JAILBREAK_ROLEPLAY = "JAILBREAK_ROLEPLAY"
    BASE64_BLOB = "BASE64_BLOB"
    SYSTEM_PROMPT_EXTRACTION = "SYSTEM_PROMPT_EXTRACTION"
    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"


@lru_cache(maxsize=None)
def get_injection_patterns() -> list[tuple[re.Pattern, InjectionMarker]]:
    """Return compiled regex patterns for prompt injection detection.

    Patterns ordered from most specific to most general to prevent false positives.
    All patterns use safe regex without nested quantifiers to avoid ReDoS.

    Returns:
        List of (compiled_regex, marker) tuples
    """
    return [
        # 1. DAN jailbreak attempts
        (re.compile(r'\b(do anything now|DAN mode|pretend you are|act as if you are)\b', re.IGNORECASE),
         InjectionMarker.JAILBREAK_DAN),

        # 2. Roleplay jailbreak attempts
        (re.compile(r'\b(in a movie|fictional scenario|hypothetical|let\'s pretend|imagine you are)\b', re.IGNORECASE),
         InjectionMarker.JAILBREAK_ROLEPLAY),

        # 3. System prompt extraction attempts
        (re.compile(r'\b(show me your|what are your|repeat your|ignore previous|print your system prompt|reveal your instructions)\b', re.IGNORECASE),
         InjectionMarker.SYSTEM_PROMPT_EXTRACTION),

        # 4. Instruction override attempts — handle verb forms (ignore/ignoring/ignored)
        #    and natural phrasing: "ignore all of my previous", "ignoring my previous", etc.
        (re.compile(r'\b(ignor(?:e|ing|ed)\s+(?:all\s+)?(?:of\s+)?(?:my\s+)?(?:the\s+)?previous|forget your instructions|new instructions|disregard prior|override system)\b', re.IGNORECASE),
         InjectionMarker.INSTRUCTION_OVERRIDE),

        # 5. Base64 blob detection (20+ chars, specific charset)
        (re.compile(r'\b([A-Za-z0-9+/]{20,}={0,2})\b'),
         InjectionMarker.BASE64_BLOB),
    ]


def detect_injection_patterns(text: str | None) -> list[str]:
    """Detect prompt injection patterns in text.

    Args:
        text: Text to analyze (can be None)

    Returns:
        List of matched marker names (e.g., ["JAILBREAK_DAN", "INSTRUCTION_OVERRIDE"])
    """
    # Handle None or non-string input
    if not isinstance(text, str):
        return []

    # Handle empty or whitespace-only text
    if not text or not text.strip():
        return []

    # Check each pattern
    matched_markers = []
    for pattern, marker in get_injection_patterns():
        if pattern.search(text):
            matched_markers.append(marker.value)
            logger.debug(f"Injection pattern detected: {marker.value}")

    return matched_markers
