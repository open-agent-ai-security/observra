# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for observra test suite."""

import pytest

from observra.core.context import initialize_session, initialize_trace
from observra.core.events import create_event


@pytest.fixture(autouse=True)
def reset_context():
    """Reset context before each test to prevent cross-test contamination."""
    initialize_session("test-session")
    initialize_trace()
    yield


@pytest.fixture
def sample_event():
    """Create a sample telemetry event for testing."""
    return create_event("test", data={"key": "value"})


@pytest.fixture
def tmp_jsonl_path(tmp_path):
    """Return path for temporary JSONL file."""
    return str(tmp_path / "test.jsonl")
