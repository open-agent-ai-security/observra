# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests verifying core/ has zero framework SDK imports and ContextVar isolation."""

import sys
from decimal import Decimal


class TestCoreIsolation:
    """Verify observra.core imports no framework SDKs."""

    def test_core_has_no_framework_imports(self):
        """Core subpackage imports no framework SDKs (CORE-02 guard)."""
        # Snapshot modules before import
        before = set(sys.modules.keys())

        import observra.core  # noqa: F401

        # Check what new modules were loaded
        after = set(sys.modules.keys())
        new_modules = after - before

        framework_modules = [
            m
            for m in new_modules
            if any(
                fw in m
                for fw in [
                    "google.adk",
                    "anthropic",
                    "openai",
                    "langchain",
                    "pydantic_ai",
                ]
            )
        ]
        assert framework_modules == [], f"Framework modules leaked into core: {framework_modules}"

    def test_base_install_no_framework_imports(self):
        """Top-level observra import loads no framework SDKs (CORE-06 guard)."""
        before = set(sys.modules.keys())

        import observra  # noqa: F401

        after = set(sys.modules.keys())
        new_modules = after - before

        # Filter out adk_telemetry compat shim (that's expected on sys.path)
        framework_modules = [
            m
            for m in new_modules
            if any(
                fw in m
                for fw in [
                    "google.adk",
                    "anthropic",
                    "openai",
                    "langchain",
                    "pydantic_ai",
                ]
            )
        ]
        assert framework_modules == [], f"Framework modules imported by base install: {framework_modules}"


class TestContextVarIsolation:
    """Verify per-framework ContextVar isolation (CORE-05 guard)."""

    def test_scoped_contexts_are_isolated(self):
        """Two framework-scoped contexts cannot read each other's values."""
        from observra.core.context import create_scoped_context

        adk_ctx = create_scoped_context("adk")
        claude_ctx = create_scoped_context("claude")

        # Set trace_id in ADK context
        adk_ctx["trace_id"].set("adk-trace-123")

        # Claude context must NOT see ADK's value
        try:
            val = claude_ctx["trace_id"].get()
            # If we get here, the vars are shared — fail
            assert False, f"Claude context read ADK's trace_id: {val}"
        except LookupError:
            pass  # Expected: Claude's ContextVar has no value set

    def test_scoped_contexts_have_independent_costs(self):
        """Two framework-scoped session_cost vars accumulate independently."""
        from observra.core.context import create_scoped_context

        adk_ctx = create_scoped_context("adk")
        claude_ctx = create_scoped_context("claude")

        adk_ctx["session_cost"].set(Decimal("1.50"))
        claude_ctx["session_cost"].set(Decimal("0.25"))

        assert adk_ctx["session_cost"].get() == Decimal("1.50")
        assert claude_ctx["session_cost"].get() == Decimal("0.25")

    def test_scoped_context_names_are_prefixed(self):
        """ContextVar debug names include framework prefix for observability."""
        from observra.core.context import create_scoped_context

        ctx = create_scoped_context("myfw")
        # ContextVar.__repr__ includes the name
        assert "myfw.trace_id" in repr(ctx["trace_id"])
        assert "myfw.session_cost" in repr(ctx["session_cost"])
