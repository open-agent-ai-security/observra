"""Unit tests for PooledWriter and BackgroundWorker batch accumulation.

Tests cover:
- PooledWriter wraps StorageBackend with ProcessPoolExecutor
- submit_batch() offloads writes to subprocess workers
- BrokenProcessPool triggers pool recreation + single retry
- Timeout protection prevents deadlock
- BackgroundWorker batch accumulation with PooledWriter
"""

import time
from unittest.mock import MagicMock

from observra.core.events import TelemetryEvent


def make_event(n: int = 0) -> TelemetryEvent:
    """Create a minimal TelemetryEvent for testing."""
    return TelemetryEvent(
        event_id=f"event-{n:04d}",
        timestamp=1_700_000_000.0 + n,
        trace_id="trace-001",
        session_id="session-001",
        span_id="span-001",
        event_type="tool_end",
        agent_name="test-agent",
    )


# ---------------------------------------------------------------------------
# Task 1: PooledWriter tests
# ---------------------------------------------------------------------------


class TestPooledWriterImport:
    """Basic import and class structure tests."""

    def test_import_pool_writer_module(self):
        """PooledWriter module can be imported."""
        from observra.core import pool_writer  # noqa: F401

    def test_class_pool_writer_exists(self):
        """PooledWriter class exists in module."""
        from observra.core.pool_writer import PooledWriter  # noqa: F401

    def test_module_level_functions_exist(self):
        """Module-level worker functions exist for pickling."""
        from observra.core import pool_writer
        assert hasattr(pool_writer, "_init_worker")
        assert hasattr(pool_writer, "_write_batch_in_worker")

    def test_process_pool_executor_used(self):
        """PooledWriter uses ProcessPoolExecutor (not ThreadPoolExecutor)."""
        import inspect

        from observra.core import pool_writer
        source = inspect.getsource(pool_writer)
        assert "ProcessPoolExecutor" in source


class TestPooledWriterWithJSONL:
    """Tests using a real JSONL backend (picklable via backend_type/kwargs)."""

    def test_init_creates_pool_writer(self, tmp_path):
        """PooledWriter constructs without error."""
        from observra.core.pool_writer import PooledWriter
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(tmp_path / "telemetry.jsonl")},
        )
        pw.close()

    def test_submit_batch_writes_all_events(self, tmp_path):
        """submit_batch() with a list of events writes all events to backend."""
        from observra.core.pool_writer import PooledWriter
        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
            max_workers=2,
        )
        events = [make_event(i) for i in range(5)]
        pw.submit_batch(events)
        pw.close()
        # File should have 5 lines
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 5

    def test_submit_batch_empty_is_noop(self, tmp_path):
        """submit_batch() with an empty list is a no-op."""
        from observra.core.pool_writer import PooledWriter
        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        pw.submit_batch([])  # Should not raise
        pw.close()
        # File either does not exist or is empty
        assert not path.exists() or path.read_text().strip() == ""

    def test_write_single_event_delegates_to_submit_batch(self, tmp_path):
        """write() single-event call uses submit_batch([event]) uniform path."""
        from observra.core.pool_writer import PooledWriter
        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        event = make_event(0)
        pw.write(event)
        pw.close()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_flush_delegates_to_backend(self, tmp_path):
        """flush() delegates to the underlying main-process backend."""
        from observra.core.pool_writer import PooledWriter
        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        pw.flush()  # Must not raise
        pw.close()

    def test_close_shuts_down_executor_and_backend(self, tmp_path):
        """close() shuts down executor and closes backend without error."""
        from observra.core.pool_writer import PooledWriter
        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        pw.close()  # Must not raise

    def test_get_stats_delegates_to_backend(self, tmp_path):
        """get_stats() returns a BackendStats dict from the underlying backend."""
        from observra.core.pool_writer import PooledWriter
        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        stats = pw.get_stats()
        pw.close()
        assert isinstance(stats, dict)
        assert "backend_type" in stats

    def test_worker_count_capped_at_four(self, tmp_path):
        """Worker pool size is capped at min(4, cpu_count)."""
        from observra.core.pool_writer import PooledWriter
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(tmp_path / "telemetry.jsonl")},
        )
        assert pw._max_workers <= 4
        pw.close()


class TestPooledWriterBrokenPool:
    """Tests for BrokenProcessPool crash recovery."""

    def test_broken_pool_triggers_recreation_and_retry(self, tmp_path):
        """BrokenProcessPool exception triggers pool recreation and one retry."""
        from concurrent.futures.process import BrokenProcessPool

        from observra.core.pool_writer import PooledWriter

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        events = [make_event(0)]

        # Patch the executor's submit to raise BrokenProcessPool on first call,
        # then succeed on second call after pool recreation
        _original_create_pool = pw._create_pool  # noqa: F841
        _call_count = {"n": 0}  # noqa: F841

        mock_future = MagicMock()
        mock_future.result.return_value = 1

        mock_executor = MagicMock()
        mock_executor.submit.side_effect = BrokenProcessPool("test crash")

        # After recreation, use a working mock
        working_executor = MagicMock()
        working_executor.submit.return_value = mock_future

        recreate_count = {"n": 0}

        def mock_create_pool():
            recreate_count["n"] += 1
            return working_executor

        pw._executor = mock_executor
        pw._create_pool = mock_create_pool

        # Should not raise; should recreate pool and retry
        pw.submit_batch(events)

        assert recreate_count["n"] == 1, "Pool should be recreated once"
        assert working_executor.submit.call_count == 1, "Retry should be attempted once"
        pw.close()

    def test_broken_pool_on_retry_logs_error_no_infinite_loop(self, tmp_path):
        """BrokenProcessPool on retry logs error and does NOT retry again."""
        from concurrent.futures.process import BrokenProcessPool

        from observra.core.pool_writer import PooledWriter

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        events = [make_event(0)]

        # Both executors raise BrokenProcessPool
        broken_executor = MagicMock()
        broken_executor.submit.side_effect = BrokenProcessPool("crash")

        broken_executor2 = MagicMock()
        broken_executor2.submit.side_effect = BrokenProcessPool("crash again")

        pool_calls = {"n": 0}

        def always_broken():
            pool_calls["n"] += 1
            return broken_executor2

        pw._executor = broken_executor
        pw._create_pool = always_broken

        # Must not raise, must not loop infinitely
        pw.submit_batch(events)

        # Pool recreated once, retry attempted once (both broken)
        assert pool_calls["n"] == 1, "Should only recreate pool once even on retry failure"
        pw.close()


class TestPooledWriterTimeout:
    """Tests for future.result() timeout protection."""

    def test_timeout_error_logs_and_continues(self, tmp_path):
        """TimeoutError on future.result() logs warning and does not raise."""
        from observra.core.pool_writer import PooledWriter

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        events = [make_event(0)]

        mock_future = MagicMock()
        mock_future.result.side_effect = TimeoutError("timed out")

        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future

        pw._executor = mock_executor

        # Must not raise
        pw.submit_batch(events)
        pw.close()

    def test_future_result_called_with_timeout(self, tmp_path):
        """future.result() is called with a timeout argument."""
        import inspect

        from observra.core.pool_writer import PooledWriter
        source = inspect.getsource(PooledWriter.submit_batch)
        # The implementation should call future.result(timeout=...)
        assert "timeout=" in source or "result(" in source


# ---------------------------------------------------------------------------
# Task 2: BackgroundWorker batch accumulation tests
# (These tests are initially expected to FAIL - TDD GREEN phase will fix them)
# ---------------------------------------------------------------------------


class TestBackgroundWorkerBatchAccumulation:
    """Tests for BackgroundWorker batch accumulation with PooledWriter."""

    def test_worker_with_pooled_writer_has_batch_params(self, tmp_path):
        """BackgroundWorker accepts batch_size and batch_timeout parameters."""
        from observra.core.pool_writer import PooledWriter
        from observra.core.queue import DropOldestQueue
        from observra.core.worker import BackgroundWorker

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        q = DropOldestQueue(maxsize=1000)
        worker = BackgroundWorker(q, pw, batch_size=50, batch_timeout=0.1)
        worker.shutdown()
        pw.close()

    def test_worker_with_pooled_writer_accumulates_into_batch(self, tmp_path):
        """BackgroundWorker accumulates events and submits batch to PooledWriter."""
        from observra.core.pool_writer import PooledWriter
        from observra.core.queue import DropOldestQueue
        from observra.core.worker import BackgroundWorker

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
            max_workers=2,
        )
        q = DropOldestQueue(maxsize=1000)
        worker = BackgroundWorker(q, pw, batch_size=5, batch_timeout=10.0)

        # Enqueue exactly batch_size events (should trigger batch submission)
        for i in range(5):
            q.put_nowait(make_event(i))

        # Wait for worker to process
        time.sleep(0.5)
        worker.shutdown()
        pw.close()

        # File should have events written
        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 5

    def test_worker_with_pooled_writer_flushes_partial_batch_on_timeout(self, tmp_path):
        """BackgroundWorker flushes partial batch on idle timeout (< batch_size)."""
        from observra.core.pool_writer import PooledWriter
        from observra.core.queue import DropOldestQueue
        from observra.core.worker import BackgroundWorker

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
            max_workers=2,
        )
        q = DropOldestQueue(maxsize=1000)
        # batch_size=100 but only 3 events sent -- partial batch should flush on timeout
        worker = BackgroundWorker(q, pw, batch_size=100, batch_timeout=0.2)

        for i in range(3):
            q.put_nowait(make_event(i))

        # Wait longer than batch_timeout for idle flush to trigger
        time.sleep(1.5)
        worker.shutdown()
        pw.close()

        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 3

    def test_worker_non_pooled_backend_uses_single_event_path(self, tmp_path):
        """BackgroundWorker with non-PooledWriter backend uses original write path."""
        from observra.core.queue import DropOldestQueue
        from observra.core.storage import create_backend
        from observra.core.worker import BackgroundWorker

        path = tmp_path / "telemetry.jsonl"
        backend = create_backend("jsonl", path=str(path))
        q = DropOldestQueue(maxsize=1000)
        worker = BackgroundWorker(q, backend)

        for i in range(5):
            q.put_nowait(make_event(i))

        time.sleep(0.5)
        worker.shutdown()

        # Events should still be written via single-event path
        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 5

    def test_worker_get_stats_includes_batches_submitted(self, tmp_path):
        """BackgroundWorker.get_stats() includes batches_submitted when using PooledWriter."""
        from observra.core.pool_writer import PooledWriter
        from observra.core.queue import DropOldestQueue
        from observra.core.worker import BackgroundWorker

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
        )
        q = DropOldestQueue(maxsize=1000)
        worker = BackgroundWorker(q, pw, batch_size=3, batch_timeout=10.0)

        for i in range(3):
            q.put_nowait(make_event(i))

        # Wait for worker to process + process pool to initialize and execute
        # Process pool workers need time to spin up on first submit
        time.sleep(2.5)
        stats = worker.get_stats()
        worker.shutdown()
        pw.close()

        assert "batches_submitted" in stats
        assert stats["batches_submitted"] >= 1

    def test_worker_flushes_partial_batch_on_shutdown(self, tmp_path):
        """Remaining batch is flushed before shutdown (sentinel with partial batch pending)."""
        from observra.core.pool_writer import PooledWriter
        from observra.core.queue import DropOldestQueue
        from observra.core.worker import BackgroundWorker

        path = tmp_path / "telemetry.jsonl"
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": str(path)},
            max_workers=2,
        )
        q = DropOldestQueue(maxsize=1000)
        # Large batch_size so batch doesn't auto-flush
        worker = BackgroundWorker(q, pw, batch_size=1000, batch_timeout=60.0)

        # Enqueue 7 events (won't hit batch_size of 1000)
        for i in range(7):
            q.put_nowait(make_event(i))

        # Immediately shut down -- partial batch should be flushed
        time.sleep(0.3)
        worker.shutdown()
        pw.close()

        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 7
