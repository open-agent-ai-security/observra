# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Deprecation decorator for the observra public API.

Provides a @deprecated decorator that emits DeprecationWarning at call time
and attaches metadata attributes for CI introspection.
"""

from __future__ import annotations

import functools
import warnings
from typing import Callable, TypeVar

_F = TypeVar("_F", bound=Callable)


def deprecated(
    *,
    removal_version: str,
    alternative: str,
    reason: str = "",
) -> Callable[[_F], _F]:
    """Mark a callable as deprecated.

    Args:
        removal_version: Version in which this symbol will be removed (e.g. "2.0").
        alternative: Replacement import path (e.g. "observra.initialize").
        reason: Additional context for the deprecation.

    The decorator preserves __wrapped__ and metadata for introspection by CI tooling.
    """

    def decorator(func: _F) -> _F:
        msg = f"{func.__qualname__} is deprecated and will be removed in v{removal_version}. Use {alternative} instead."
        if reason:
            msg += f" Reason: {reason}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        wrapper.__deprecated__ = True  # type: ignore[attr-defined]
        wrapper.__removal_version__ = removal_version  # type: ignore[attr-defined]
        wrapper.__deprecation_alternative__ = alternative  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
