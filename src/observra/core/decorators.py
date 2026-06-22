# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Level 3 instrumentation decorators: @tool and @model_call.

These decorators let users instrument any function in their agent code so the
library can capture CIM-compliant events even when the underlying framework
cannot provide the data natively.

Usage::

    import observra

    observra.initialize(backend="jsonl", path="telemetry.jsonl")

    # Works with ANY framework — or no framework at all
    @observra.tool
    def search_web(query: str) -> str:
        return requests.get(f"https://api.example.com?q={query}").text

    @observra.tool(name="lookup_user", capture_data=True)
    def get_user(user_id: int) -> dict:
        return db.users.find(user_id)

    @observra.model_call(model="gpt-4o")
    def ask_llm(prompt: str) -> str:
        resp = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
    # → emits model_request + model_response with estimated tokens + cost_usd
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_prompt(args: tuple, kwargs: dict, prompt_arg: str | int | None) -> str:
    """Extract prompt text from function arguments.

    Priority:
    1. Explicit ``prompt_arg`` name or index.
    2. First ``str`` found in positional args.
    3. First ``str`` found in keyword args.
    4. Empty string fallback (token estimation will return 0).
    """
    if prompt_arg is not None:
        if isinstance(prompt_arg, int) and 0 <= prompt_arg < len(args):
            return str(args[prompt_arg] or "")
        if isinstance(prompt_arg, str) and prompt_arg in kwargs:
            return str(kwargs[prompt_arg] or "")

    for arg in args:
        if isinstance(arg, str):
            return arg
    for val in kwargs.values():
        if isinstance(val, str):
            return val
    return ""


def _extract_response_text(result: Any) -> str:
    """Extract plain text from a function return value.

    Handles: str, OpenAI ChatCompletion, objects with .content/.text attributes.
    Falls back to str(result) for anything else.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result

    # OpenAI ChatCompletion: result.choices[0].message.content
    if hasattr(result, "choices"):
        try:
            choice = result.choices[0]
            content = getattr(getattr(choice, "message", None), "content", None)
            if isinstance(content, str):
                return content
        except Exception:
            pass

    # Anthropic / Claude SDK: result.content (list of blocks or str)
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            getattr(block, "text", "") or ""
            for block in content
            if hasattr(block, "text")
        )

    # Generic: result.text
    text = getattr(result, "text", None)
    if text is not None:
        return str(text)

    return str(result)


# ── @tool ─────────────────────────────────────────────────────────────────────

def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    capture_data: bool = False,
    payload_max_bytes: int = 4096,
):
    """Instrument any function as a CIM tool call.

    Emits ``tool_start`` before the function runs and ``tool_end`` after it
    returns (or ``tool_error`` if it raises). Works with both sync and async
    functions. Safe to use alongside any framework adapter — the dedup registry
    prevents double-counting when the framework also captures the same call.

    Usage::

        # Bare decorator — tool name from function name
        @observra.tool
        def search_web(query: str) -> str: ...

        # With options
        @observra.tool(name="web_search", capture_data=True)
        def search_web(query: str) -> str: ...

        # Async
        @observra.tool
        async def fetch_data(url: str) -> str: ...

    Args:
        func: The function to decorate (when used bare without parentheses).
        name: Override the tool name. Defaults to ``func.__name__``.
        capture_data: If True, serialise args/result into ``tool_args``/
                      ``tool_result``. Default False for privacy.
        payload_max_bytes: Max bytes for serialisation (default 4096).

    Emits:
        ``tool_start`` — before the function runs
        ``tool_end``   — on success, includes ``duration_ms``
        ``tool_error`` — on exception, includes ``error_message``, ``error_type_name``, ``is_retryable``
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            _log, safe_serialize = _lazy_imports()

            tool_args_str = _build_tool_args(args, kwargs, capture_data, safe_serialize, payload_max_bytes)
            _log.tool_start(tool_name, tool_args=tool_args_str)
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                duration_ms = (time.monotonic() - start) * 1000.0
                result_str = safe_serialize(result, payload_max_bytes) if capture_data else None
                _log.tool_end(tool_name, duration_ms=duration_ms, tool_result=result_str)
                return result
            except Exception as exc:
                _log.tool_error(tool_name, error=exc)
                raise

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            _log, safe_serialize = _lazy_imports()

            tool_args_str = _build_tool_args(args, kwargs, capture_data, safe_serialize, payload_max_bytes)
            _log.tool_start(tool_name, tool_args=tool_args_str)
            start = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                duration_ms = (time.monotonic() - start) * 1000.0
                result_str = safe_serialize(result, payload_max_bytes) if capture_data else None
                _log.tool_end(tool_name, duration_ms=duration_ms, tool_result=result_str)
                return result
            except Exception as exc:
                _log.tool_error(tool_name, error=exc)
                raise

        return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper

    # Support both @tool and @tool(...)
    if func is not None:
        return decorator(func)
    return decorator


# ── @model_call ───────────────────────────────────────────────────────────────

def model_call(
    func: Callable | None = None,
    *,
    model: str = "unknown",
    prompt_arg: str | int | None = None,
    capture_data: bool = False,
    payload_max_bytes: int = 4096,
):
    """Instrument any LLM call as a CIM model_request/model_response pair.

    When the framework doesn't expose token counts, this decorator estimates
    them from the prompt and response text using tiktoken (same technique as
    the Claude adapter). Cost is calculated from the bundled pricing table.

    Usage::

        @observra.model_call(model="gpt-4o")
        def ask_llm(prompt: str) -> str:
            resp = openai.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content

        # Specify which arg holds the prompt (by name or index)
        @observra.model_call(model="claude-opus-4-6", prompt_arg="user_message")
        def call_claude(system: str, user_message: str) -> str: ...

        # Async
        @observra.model_call(model="gpt-4o")
        async def ask_llm_async(prompt: str) -> str: ...

    Args:
        model: Model identifier for pricing lookup (e.g. ``"gpt-4o"``).
        prompt_arg: Name or index of the arg containing the prompt text.
                    Defaults to the first ``str`` argument found.
        capture_data: Reserved for future use. Model data is not captured by default.
        payload_max_bytes: Max bytes for serialisation (default 4096).

    Emits:
        ``model_request``  — before the function runs
        ``model_response`` — on success, with estimated ``input_tokens``,
                             ``output_tokens``, ``total_tokens``, ``cost_usd``
        ``model_error``    — on exception, with ``error_message``, ``error_type_name``
    """
    def decorator(fn: Callable) -> Callable:

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            _log, _ = _lazy_imports()
            from observra.adapters.utils import estimate_tokens

            prompt_text = _extract_prompt(args, kwargs, prompt_arg)
            _log.model_request(model)
            try:
                result = fn(*args, **kwargs)
                response_text = _extract_response_text(result)
                input_tokens = estimate_tokens(prompt_text) if prompt_text else 0
                output_tokens = estimate_tokens(response_text) if response_text else 0
                _log.model_response(model, input_tokens=input_tokens, output_tokens=output_tokens)
                return result
            except Exception as exc:
                _log.model_error(model_name=model, error=exc)
                raise

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            _log, _ = _lazy_imports()
            from observra.adapters.utils import estimate_tokens

            prompt_text = _extract_prompt(args, kwargs, prompt_arg)
            _log.model_request(model)
            try:
                result = await fn(*args, **kwargs)
                response_text = _extract_response_text(result)
                input_tokens = estimate_tokens(prompt_text) if prompt_text else 0
                output_tokens = estimate_tokens(response_text) if response_text else 0
                _log.model_response(model, input_tokens=input_tokens, output_tokens=output_tokens)
                return result
            except Exception as exc:
                _log.model_error(model_name=model, error=exc)
                raise

        return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


# ── Private helpers ───────────────────────────────────────────────────────────

def _lazy_imports():
    """Late-bind log module and safe_serialize to avoid circular imports."""
    import observra.log as _log
    from observra.adapters.utils import safe_serialize
    return _log, safe_serialize


def _build_tool_args(
    args: tuple,
    kwargs: dict,
    capture_data: bool,
    safe_serialize: Callable,
    payload_max_bytes: int,
) -> Optional[str]:
    """Serialise function arguments into a string if capture_data is True."""
    if not capture_data or (not args and not kwargs):
        return None
    payload: dict = {}
    if args:
        payload["args"] = list(args)
    if kwargs:
        payload["kwargs"] = kwargs
    return safe_serialize(payload, payload_max_bytes)
