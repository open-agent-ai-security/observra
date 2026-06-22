"""Unit tests for events module."""

from dataclasses import FrozenInstanceError

import pytest

from observra.core.events import TelemetryEvent, create_event


def test_create_event_has_required_fields():
    """Test that create_event populates all required fields."""
    event = create_event('test', data={'key': 'value'})

    assert event.event_id
    assert event.timestamp > 0
    assert event.trace_id
    assert event.session_id
    assert event.span_id
    assert event.event_type == 'test'


def test_create_event_with_kwargs():
    """Test create_event with tool_name and other kwargs."""
    event = create_event('test', tool_name="test_tool", custom_field="value")

    assert event.tool_name == "test_tool"
    assert event.data is not None


def test_create_event_frozen():
    """Test that TelemetryEvent is immutable."""
    event = create_event('test', data={'key': 'value'})

    with pytest.raises(FrozenInstanceError):
        event.event_type = 'modified'


def test_create_event_validates_empty_type():
    """Test that empty event_type raises ValueError."""
    with pytest.raises(ValueError, match="event_type cannot be empty"):
        TelemetryEvent(
            event_id="test",
            timestamp=1234.5,
            trace_id="trace",
            session_id="session",
            span_id="span",
            event_type=""
        )


def test_create_event_hot_path_strips_strings():
    """Test that hot path event types strip string values."""
    event = create_event(
        'model_request',
        input_tokens=100,
        output_tokens=50,
        model="gemini-2.5-flash",
        user_content="some text"
    )

    # String values are replaced with None (keys retained for uniform schema)
    assert event.data is not None
    assert event.data.get('user_content') is None
    assert event.data.get('model') is None

    # Numeric values should be preserved
    assert event.data['input_tokens'] == 100
    assert event.data['output_tokens'] == 50


def test_create_event_cold_path_redacts():
    """Test that cold path event types apply redaction."""
    event = create_event(
        'model_error',
        error_message="Failed with api_key=sk_test_abc123def456ghi"
    )

    # String should be redacted
    assert event.data is not None
    assert 'error_message' in event.data
    assert '[REDACTED:API_KEY]' in event.data['error_message']
    assert 'sk_test_abc123def456ghi' not in event.data['error_message']
