# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Shared token normalization utilities for framework adapters.

Provides NormalizedTokens dataclass and per-framework normalize_*_tokens()
functions. All adapters import from here to maintain a single canonical token
shape across ADK, Claude, OpenAI, pydantic-ai, and future integrations.

Also provides shared safe_serialize() and estimate_tokens() utilities used
by ADK, Claude, OpenAI, and future framework adapters.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-cached tiktoken tokenizer (initialized on first call to estimate_tokens)
_TOKENIZER = None

# Set to True to disable tiktoken loading (e.g., in test environments or when
# tiktoken's C extension is known to be incompatible with the current Python version).
# When True, estimate_tokens() falls back to the char/4 heuristic immediately.
TIKTOKEN_DISABLED: bool = False


@dataclass(frozen=True)
class NormalizedTokens:
    """Canonical token usage shape shared across all framework adapters.

    Required fields hold the minimum token counts every adapter provides.
    Optional extended fields use None (not 0) to distinguish "not reported"
    from "zero usage" — downstream analytics can filter on IS NOT NULL.

    Attributes:
        input_tokens: Tokens consumed by the prompt / input context.
        output_tokens: Tokens generated in the model response.
        total_tokens: Total tokens for this call (may differ from input+output
                      when the API reports a separate total).
        cached_tokens: Tokens served from the prompt cache (None if not reported).
        reasoning_tokens: Tokens used for chain-of-thought / thinking steps
                          (None if the model does not expose them).
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_tokens: Optional[int] = field(default=None)
    reasoning_tokens: Optional[int] = field(default=None)


def normalize_adk_tokens(usage_metadata) -> Optional[NormalizedTokens]:
    """Convert ADK usage_metadata to a NormalizedTokens instance.

    Uses duck typing via getattr — no hard dependency on google-adk.
    Safe to call with any object that exposes the expected attributes.

    ADK field mapping:
        prompt_token_count          -> input_tokens
        candidates_token_count      -> output_tokens
        total_token_count           -> total_tokens
        cached_content_token_count  -> cached_tokens  (None if absent/falsy)
        thoughts_token_count        -> reasoning_tokens (None if absent/falsy)

    Args:
        usage_metadata: ADK UsageMetadata object or any duck-typed equivalent.
                        Pass None to get None back (no-op).

    Returns:
        NormalizedTokens if usage_metadata is not None, else None.
    """
    if usage_metadata is None:
        return None

    input_tokens = getattr(usage_metadata, 'prompt_token_count', 0) or 0
    output_tokens = getattr(usage_metadata, 'candidates_token_count', 0) or 0
    total_tokens = getattr(usage_metadata, 'total_token_count', 0) or 0

    # Extended fields: keep None sentinel for "not reported" vs "zero usage"
    cached_raw = getattr(usage_metadata, 'cached_content_token_count', None)
    cached_tokens = cached_raw if cached_raw else None

    reasoning_raw = getattr(usage_metadata, 'thoughts_token_count', None)
    reasoning_tokens = reasoning_raw if reasoning_raw else None

    return NormalizedTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def normalize_openai_tokens(usage: dict | None) -> Optional[NormalizedTokens]:
    """Convert OpenAI Agents SDK usage dict to NormalizedTokens.

    The usage dict comes from GenerationSpanData.usage with these keys:
        input_tokens, output_tokens, total_tokens,
        input_tokens_details.cached_tokens,
        output_tokens_details.reasoning_tokens

    IMPORTANT: reasoning_tokens is a SUBSET of output_tokens — do NOT add them
    separately for cost calculation. Track separately for observability only.

    Args:
        usage: GenerationSpanData.usage dict or None.

    Returns:
        NormalizedTokens if usage is not None and has data, else None.
    """
    if not usage:
        return None

    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", 0) or 0)

    # Cached tokens from nested input_tokens_details
    input_details = usage.get("input_tokens_details") or {}
    cached_raw = input_details.get("cached_tokens")
    cached_tokens = int(cached_raw) if cached_raw else None

    # Reasoning tokens from nested output_tokens_details (subset of output_tokens)
    output_details = usage.get("output_tokens_details") or {}
    reasoning_raw = output_details.get("reasoning_tokens")
    reasoning_tokens = int(reasoning_raw) if reasoning_raw else None

    return NormalizedTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def normalize_langchain_tokens(response) -> Optional[NormalizedTokens]:
    """Convert LangChain LLMResult to NormalizedTokens.

    Extraction strategy (in priority order):
    1. response.generations[0][0].message.usage_metadata — modern, provider-agnostic
       (works for ChatOpenAI, ChatAnthropic, ChatGoogleGenerativeAI)
    2. response.llm_output["token_usage"] — ChatOpenAI legacy (prompt_tokens/completion_tokens)
    3. response.llm_output["usage"] — ChatAnthropic (input_tokens/output_tokens)
    4. Returns None if no token data available

    Uses getattr() for all field access (duck typing, no hard dependency on langchain-core types).
    Always wraps in try/except returning None on any failure.

    ChatOpenAI token_usage keys:  prompt_tokens, completion_tokens, total_tokens
    ChatAnthropic usage keys:     input_tokens, output_tokens, (total not always present)
    usage_metadata keys:          input_tokens, output_tokens, total_tokens (standardized)

    Args:
        response: LangChain LLMResult from BaseCallbackHandler.on_llm_end.
                  Pass None to get None back (no-op).

    Returns:
        NormalizedTokens if token data is available, else None.
    """
    if response is None:
        return None

    # --- Path 1: AIMessage.usage_metadata (modern, provider-agnostic) ---
    try:
        gen = getattr(response, "generations", None)
        if gen and gen[0]:
            first_gen = gen[0][0]
            message = getattr(first_gen, "message", None)
            if message is not None:
                usage_metadata = getattr(message, "usage_metadata", None)
                if usage_metadata:
                    input_tokens = int(usage_metadata.get("input_tokens", 0) or 0)
                    output_tokens = int(usage_metadata.get("output_tokens", 0) or 0)
                    total_tokens = int(usage_metadata.get("total_tokens", 0) or 0)
                    if input_tokens or output_tokens:
                        # Extract cached_tokens from input_token_details if present
                        input_details = usage_metadata.get("input_token_details") or {}
                        cached_raw = input_details.get("cache_read") or input_details.get("cached_tokens")
                        cached_tokens = int(cached_raw) if cached_raw else None
                        return NormalizedTokens(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens or (input_tokens + output_tokens),
                            cached_tokens=cached_tokens,
                            reasoning_tokens=None,  # Not exposed in usage_metadata currently
                        )
    except Exception:
        pass

    # --- Path 2: llm_output["token_usage"] (ChatOpenAI legacy) ---
    try:
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage") or {}
        if token_usage:
            input_tokens = int(token_usage.get("prompt_tokens", 0) or 0)
            output_tokens = int(token_usage.get("completion_tokens", 0) or 0)
            total_tokens = int(token_usage.get("total_tokens", 0) or 0)
            if input_tokens or output_tokens:
                return NormalizedTokens(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens or (input_tokens + output_tokens),
                    cached_tokens=None,
                    reasoning_tokens=None,
                )

        # --- Path 3: llm_output["usage"] (ChatAnthropic) ---
        usage = llm_output.get("usage") or {}
        if usage:
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            total_tokens = int(usage.get("total_tokens", 0) or 0)
            if input_tokens or output_tokens:
                return NormalizedTokens(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens or (input_tokens + output_tokens),
                    cached_tokens=None,
                    reasoning_tokens=None,
                )
    except Exception:
        pass

    return None


def safe_serialize(obj, max_length: int = 4096) -> str:
    """Convert tool args/results to a string safe for telemetry storage.

    Shared utility for all framework adapters (ADK, Claude, etc.).
    Handles dicts, lists, and arbitrary types. Truncates large values
    to prevent event bloat. The result goes through cold path redaction
    (PII/credential scrubbing) via create_event.

    Args:
        obj: Tool arguments or result to serialize
        max_length: Max string length before truncation

    Returns:
        String representation of the object
    """
    try:
        if isinstance(obj, (dict, list)):
            text = json.dumps(obj, default=str, ensure_ascii=False)
        elif isinstance(obj, str):
            text = obj
        else:
            # ADK tool results / arbitrary objects
            text = str(obj)
    except Exception:
        text = repr(obj)

    if len(text) > max_length:
        return text[:max_length] + f"... [truncated, {len(text)} chars total]"
    return text


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string using tiktoken cl100k_base encoding.

    Accuracy note: ~10-20% error for Claude models (which use their own tokenizer).
    Falls back to the Anthropic-documented ~3.5 chars/token heuristic if tiktoken
    is not installed or encoding fails.

    Args:
        text: Text to estimate token count for

    Returns:
        Estimated number of tokens (always >= 1)
    """
    global _TOKENIZER
    if TIKTOKEN_DISABLED:
        return max(1, len(text) // 4) if text else 0
    try:
        if _TOKENIZER is None:
            import tiktoken
            _TOKENIZER = tiktoken.get_encoding("cl100k_base")
        return len(_TOKENIZER.encode(text))
    except Exception:
        # ImportError (tiktoken not installed) or any encoding error
        # Fallback: Anthropic's ~3.5 chars/token heuristic, rounded
        return max(1, len(text) // 4) if text else 0
