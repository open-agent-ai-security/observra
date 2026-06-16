"""Pydantic AI adapter for agent telemetry.

Requires: pip install observra[pydantic-ai]
"""
try:
    from .adapter import PydanticAIAdapter
    __all__ = ["PydanticAIAdapter"]
except ImportError:
    # opentelemetry-sdk not installed — base install is unaffected
    pass
