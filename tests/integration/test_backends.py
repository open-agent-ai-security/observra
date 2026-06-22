# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for storage backends."""

import json

from observra.backends.jsonl import JSONLBackend
from observra.core.events import create_event
from observra.core.storage import create_backend


def test_jsonl_write_and_read(tmp_jsonl_path):
    """Test JSONLBackend writes events to file."""
    backend = JSONLBackend(path=tmp_jsonl_path)

    # Create and write event
    event = create_event("test", data={"key": "value"})
    backend.write(event)
    backend.flush()

    # Read file contents
    with open(tmp_jsonl_path, "r") as f:
        lines = f.readlines()

    # Verify JSON line contains event_id
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event_id"] == event.event_id
    assert data["event_type"] == "test"

    backend.close()


def test_jsonl_stats(tmp_jsonl_path):
    """Test JSONLBackend statistics tracking."""
    backend = JSONLBackend(path=tmp_jsonl_path)

    # Write multiple events
    for i in range(5):
        event = create_event("test", data={"count": i})
        backend.write(event)

    backend.flush()
    stats = backend.get_stats()

    # Check stats
    assert stats["event_count"] == 5
    assert stats["bytes_written"] > 0

    backend.close()


def test_jsonl_close_flushes(tmp_jsonl_path):
    """Test JSONLBackend close flushes buffered writes."""
    backend = JSONLBackend(path=tmp_jsonl_path)

    # Write event
    event = create_event("test", data={"key": "value"})
    backend.write(event)

    # Close without explicit flush
    backend.close()

    # Verify file has content
    with open(tmp_jsonl_path, "r") as f:
        content = f.read()

    assert len(content) > 0
    assert "event_id" in content


def test_create_backend_factory_jsonl(tmp_jsonl_path):
    """Test create_backend factory for JSONL backend."""
    backend = create_backend("jsonl", path=tmp_jsonl_path)

    assert isinstance(backend, JSONLBackend)

    backend.close()


def test_create_backend_unknown():
    """Test create_backend raises ValueError for unknown backend."""
    try:
        create_backend("unknown")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "unknown" in str(e).lower()
