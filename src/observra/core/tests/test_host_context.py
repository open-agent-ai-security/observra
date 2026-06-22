# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``observra.core.host_context``."""

from __future__ import annotations

from observra.core.host_context import HostContext, get_host_context


def test_host_context_resolves_or_stays_none() -> None:
    ctx = get_host_context()
    assert isinstance(ctx, HostContext)
    # arch and library_version are always populated.
    assert ctx.arch, "arch must be set"
    assert ctx.library_version, "library_version must be set"
    # host or user should resolve in any normal Python process.
    assert ctx.host or ctx.user, "expected at least one of host/user to resolve"


def test_host_context_arch_normalized_to_rust_naming() -> None:
    ctx = get_host_context()
    # macOS reports arm64 via uname; Rust calls it aarch64. We must match Rust.
    assert ctx.arch != "arm64", (
        "arch should be normalized to aarch64, not arm64, to match the Rust forwarder"
    )
    # Common values we should produce: aarch64, x86_64, x86, riscv64, etc.
    # Just assert no spaces.
    assert " " not in ctx.arch


def test_host_context_is_cached_singleton() -> None:
    a = get_host_context()
    b = get_host_context()
    assert a is b, "get_host_context must return the cached instance"
