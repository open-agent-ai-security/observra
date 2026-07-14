# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Public API behavior tests for package-level ergonomics and lifecycle safety."""

import pytest

import observra as telemetry
from observra.core.events import create_event


@pytest.fixture(autouse=True)
def _cleanup_pipeline():
    """Ensure module-level async pipeline state is reset per test."""
    yield
    worker = getattr(telemetry, "_worker", None)
    if worker is not None:
        worker._shutdown()
    telemetry._worker = None
    telemetry._queue = None
    telemetry._queue_proxy.set_target(None)


def test_import_star_does_not_raise_for_missing_optional_adapters():
    """Wildcard import must not fail when optional adapter extras are absent."""
    namespace = {}
    exec("from observra import *", namespace, namespace)
    assert "initialize" in namespace
    assert set(telemetry.__all__).issubset(set(namespace.keys()))


def test_initialize_invalid_backend_raises_value_error():
    """initialize() must fail fast for unknown backend types."""
    with pytest.raises(ValueError, match="Unknown backend type"):
        telemetry.initialize(backend="does-not-exist")


def test_initialize_replaces_existing_worker(tmp_path):
    """Repeated initialize() should replace old worker instead of leaking threads."""
    path1 = tmp_path / "telemetry1.jsonl"
    path2 = tmp_path / "telemetry2.jsonl"

    telemetry.initialize(backend="jsonl", path=str(path1))
    old_worker = telemetry._worker
    assert old_worker is not None
    assert old_worker._thread.is_alive()

    telemetry.initialize(backend="jsonl", path=str(path2))
    new_worker = telemetry._worker
    assert new_worker is not None
    assert new_worker is not old_worker
    assert new_worker._thread.is_alive()
    assert not old_worker._thread.is_alive()


def test_initialize_failure_keeps_existing_pipeline(tmp_path):
    """A failed reinitialize attempt must not tear down a healthy pipeline."""
    path1 = tmp_path / "telemetry.jsonl"
    telemetry.initialize(backend="jsonl", path=str(path1))

    old_worker = telemetry._worker
    assert old_worker is not None
    assert old_worker._thread.is_alive()

    with pytest.raises(ValueError, match="Unknown backend type"):
        telemetry.initialize(backend="does-not-exist")

    assert telemetry._worker is old_worker
    assert telemetry._worker._thread.is_alive()


def test_plugin_survives_reinit(tmp_path):
    """Adapters created before re-init should enqueue to the new queue."""
    import time

    path1 = tmp_path / "telemetry1.jsonl"
    path2 = tmp_path / "telemetry2.jsonl"

    telemetry.initialize(backend="jsonl", path=str(path1))
    plugin = telemetry.create_plugin()

    # Re-initialize with a different backend
    telemetry.initialize(backend="jsonl", path=str(path2))
    new_queue = telemetry._queue

    # Emit through the old plugin — should reach the NEW queue
    event = create_event("test_event", data={"after_reinit": True})
    plugin._queue.put_nowait(event)

    # Give the worker a moment to drain
    time.sleep(0.1)
    assert new_queue.get_stats()["enqueued"] >= 1


# ── Public API Surface Stability ─────────────────────────────────────────────

_PUBLIC_API_STABLE_SURFACE = frozenset(
    {
        "initialize",
        "create_plugin",
        "create_logging_handler",
        "emit",
        "initialize_session",
        "get_stats",
        "get_metrics",  # Phase 38 OBS-01: stable self-metrics API
        "observability",  # Phase 38 OBS-01: observability module
        "TelemetryEvent",
        "StorageBackend",
        "ADKAdapter",
        "ClaudeAdapter",
        "OpenAIAdapter",
        "LangChainAdapter",
        "PydanticAIAdapter",
    }
)


def test_public_api_snapshot():
    """public.py __all__ matches the frozen v1.0 surface manifest (D-04)."""
    import observra.public as pub

    assert set(pub.__all__) == _PUBLIC_API_STABLE_SURFACE, (
        "Public API surface has drifted. Update _PUBLIC_API_STABLE_SURFACE deliberately if this change is intentional."
    )


def test_public_api_import_does_not_leak_framework_sdks():
    """Importing observra.public must not trigger framework SDK imports."""
    import sys

    before = set(sys.modules.keys())
    import observra.public  # noqa: F401

    after = set(sys.modules.keys())
    new_mods = after - before
    framework_modules = [
        m
        for m in new_mods
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
    assert framework_modules == [], f"Framework modules leaked: {framework_modules}"
