# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for detection module."""

from observra.core.detection import (
    MAX_DELEGATION_DEPTH,
    classify_error,
    decrement_delegation_depth,
    get_delegation_depth,
    increment_delegation_depth,
    initialize_delegation_depth,
)


def test_classify_rate_limit():
    """Test classification of rate limit errors."""
    error = Exception("429 Too Many Requests")
    error_type, is_retryable = classify_error(error, "model")

    assert error_type == "rate_limit"
    assert is_retryable is True


def test_classify_auth():
    """Test classification of authentication errors."""
    error = Exception("401 Unauthorized")
    error_type, is_retryable = classify_error(error, "model")

    assert error_type == "auth"
    assert is_retryable is False


def test_classify_network():
    """Test classification of network errors."""
    error = ConnectionError("timeout")
    error_type, is_retryable = classify_error(error, "model")

    assert error_type == "network"
    assert is_retryable is True


def test_classify_default_model():
    """Test default classification for model context."""
    error = Exception("something went wrong")
    error_type, is_retryable = classify_error(error, "model")

    assert error_type == "model_error"
    assert is_retryable is False


def test_classify_default_tool():
    """Test default classification for tool context."""
    error = Exception("something went wrong")
    error_type, is_retryable = classify_error(error, "tool")

    assert error_type == "tool_error"
    assert is_retryable is False


def test_delegation_depth_increment():
    """Test delegation depth increment."""
    initialize_delegation_depth()
    assert get_delegation_depth() == 0

    new_depth, exceeded = increment_delegation_depth()

    assert new_depth == 1
    assert exceeded is False
    assert get_delegation_depth() == 1


def test_delegation_depth_exceed():
    """Test delegation depth exceeds maximum."""
    initialize_delegation_depth()

    # Increment MAX_DELEGATION_DEPTH times (should not exceed)
    for _ in range(MAX_DELEGATION_DEPTH):
        depth, exceeded = increment_delegation_depth()
        if depth <= MAX_DELEGATION_DEPTH:
            assert exceeded is False

    # One more increment should exceed
    depth, exceeded = increment_delegation_depth()
    assert exceeded is True
    assert depth == MAX_DELEGATION_DEPTH + 1


def test_delegation_depth_decrement_underflow():
    """Test delegation depth decrement protects against underflow."""
    initialize_delegation_depth()
    assert get_delegation_depth() == 0

    # Decrement should not go negative
    new_depth = decrement_delegation_depth()
    assert new_depth == 0
    assert get_delegation_depth() == 0
