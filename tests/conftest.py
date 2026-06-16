"""Shared fixtures for aba_telemetry test suite."""

import pytest

from aba_telemetry.core.context import initialize_session, initialize_trace
from aba_telemetry.core.events import create_event


@pytest.fixture(autouse=True)
def reset_context():
    """Reset context before each test to prevent cross-test contamination."""
    initialize_session("test-session")
    initialize_trace()
    yield


@pytest.fixture
def sample_event():
    """Create a sample telemetry event for testing."""
    return create_event('test', data={'key': 'value'})


@pytest.fixture
def tmp_jsonl_path(tmp_path):
    """Return path for temporary JSONL file."""
    return str(tmp_path / "test.jsonl")


