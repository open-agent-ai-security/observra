# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""LangChain/LangGraph adapter for agent telemetry.

Requires: pip install observra[langchain]
"""

try:
    from .adapter import LangChainAdapter
    __all__ = ["LangChainAdapter"]
except ImportError:
    # langchain-core not installed — base install is unaffected
    pass
