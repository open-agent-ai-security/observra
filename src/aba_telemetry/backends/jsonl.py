"""JSONL storage backend with file rotation support."""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Optional, TextIO

from aba_telemetry.core.events import TelemetryEvent
from aba_telemetry.core.types import BackendStats

logger = logging.getLogger(__name__)

# Optional encryption support (aba-telemetry[encryption])
try:
    from aba_telemetry.core.encryption import EncryptionProvider as _EncryptionProvider
    _ENCRYPTION_AVAILABLE = True
except ImportError:
    _EncryptionProvider = None  # type: ignore[assignment,misc]
    _ENCRYPTION_AVAILABLE = False


class JSONLBackend:
    """JSONL storage backend with size-based file rotation.

    Writes telemetry events as JSON lines (one event per line).
    Automatically rotates files when they exceed max_bytes.

    File rotation strategy:
        base.jsonl -> base.jsonl.1 -> base.jsonl.2 -> ... -> base.jsonl.N
        Oldest files beyond backup_count are deleted.

    Args:
        path: Base file path for JSONL output (default: "telemetry.jsonl")
        max_bytes: Maximum file size before rotation (default: 10MB)
        backup_count: Number of rotated backups to keep (default: 5)
    """

    def __init__(
        self,
        path: str | Path = "telemetry.jsonl",
        max_bytes: int = 10_485_760,
        backup_count: int = 5,
        encryption_key: Optional[bytes] = None,
    ):
        self._encryption: Optional[_EncryptionProvider] = None
        if encryption_key is not None:
            if not _ENCRYPTION_AVAILABLE:
                raise RuntimeError(
                    "cryptography package not installed. "
                    "Run: pip install aba-telemetry[encryption]"
                )
            self._encryption = _EncryptionProvider(encryption_key)

        # Encrypted files get .enc extension to signal they require decryption.
        base_path = Path(path)
        if self._encryption is not None and not str(base_path).endswith('.enc'):
            base_path = base_path.parent / (base_path.name + '.enc')

        self._path = base_path
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        # Create parent directories if needed
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Open file handle in append mode
        self._file: Optional[TextIO] = open(self._path, 'a', encoding='utf-8')

        # Initialize stats counters
        self._stats = {
            'events_written': 0,
            'errors': 0,
            'bytes_written': 0,
            'rotations': 0
        }

        # Track oldest/newest timestamps in-memory (O(1) per write, resets on restart)
        self._oldest_ts: float | None = None
        self._newest_ts: float | None = None

        logger.debug(f"Initialized JSONLBackend: path={self._path}, max_bytes={max_bytes}, encrypted={self._encryption is not None}")

    def write(self, event: TelemetryEvent) -> None:
        """Write a single event as a JSON line.

        Args:
            event: TelemetryEvent to write
        """
        if not self._file:
            logger.warning("Cannot write to closed backend")
            self._stats['errors'] += 1
            return

        try:
            # Convert event to dict
            data = asdict(event)

            # Serialize to JSON (compact format, handle non-serializable types)
            line = json.dumps(data, separators=(',', ':'), default=str)

            # Encrypt if encryption provider is configured (encrypt-then-append)
            if self._encryption is not None:
                line = self._encryption.encrypt_line(line)

            # Write line with newline and flush immediately
            self._file.write(line + '\n')
            self._file.flush()

            # Update stats
            self._stats['events_written'] += 1
            self._stats['bytes_written'] += len(line) + 1

            # Track timestamp range for get_stats()
            ts = data.get('timestamp')
            if ts is not None:
                if self._oldest_ts is None:
                    self._oldest_ts = float(ts)
                self._newest_ts = float(ts)

            # Check if rotation needed
            if self._should_rollover():
                self._do_rollover()

        except Exception as e:
            logger.warning(f"Failed to write event: {e}")
            self._stats['errors'] += 1

    def _should_rollover(self) -> bool:
        """Check if file rotation is needed.

        Returns:
            True if file size exceeds max_bytes
        """
        if not self._file:
            return False

        try:
            # Flush to ensure accurate file size
            self._file.flush()
            return self._path.stat().st_size >= self.max_bytes
        except Exception:
            return False

    def _do_rollover(self) -> None:
        """Perform file rotation.

        Rotates existing backups in reverse order and creates fresh file.
        """
        try:
            # Close current file
            if self._file:
                self._file.close()

            # Rotate existing backups in reverse order
            for i in range(self.backup_count - 1, 0, -1):
                src = Path(f"{self._path}.{i}")
                dst = Path(f"{self._path}.{i + 1}")
                if src.exists():
                    if dst.exists():
                        dst.unlink()
                    src.rename(dst)

            # Delete oldest if at limit
            oldest = Path(f"{self._path}.{self.backup_count + 1}")
            if oldest.exists():
                oldest.unlink()

            # Rename current file to .1
            if self._path.exists():
                dst = Path(f"{self._path}.1")
                if dst.exists():
                    dst.unlink()
                self._path.rename(dst)

            # Open fresh file handle
            self._file = open(self._path, 'a', encoding='utf-8')

            # Update rotation counter
            self._stats['rotations'] += 1

            logger.info(f"Rotated log file: {self._path} (rotation #{self._stats['rotations']})")

        except Exception as e:
            logger.error(f"Failed to rotate file: {e}")
            self._stats['errors'] += 1
            # Try to reopen current file
            try:
                self._file = open(self._path, 'a', encoding='utf-8')
            except Exception:
                self._file = None

    def flush(self) -> None:
        """Flush buffered writes to disk."""
        if self._file:
            try:
                self._file.flush()
            except Exception as e:
                logger.warning(f"Failed to flush: {e}")
                self._stats['errors'] += 1

    def close(self) -> None:
        """Close the backend and release resources."""
        if self._file:
            try:
                self._file.flush()
                self._file.close()
            except Exception as e:
                logger.warning(f"Failed to close cleanly: {e}")
                self._stats['errors'] += 1
            finally:
                self._file = None
            logger.debug(f"Closed JSONLBackend: {self._path}")

    def get_stats(self) -> BackendStats:
        """Get backend statistics.

        Returns:
            BackendStats with bytes_written, event_count, backend_type,
            oldest_event_ts, newest_event_ts.

        Note: oldest_event_ts and newest_event_ts reflect only events written
        in the current process session. They reset to None on restart.
        """
        return BackendStats(
            bytes_written=self._stats['bytes_written'],
            event_count=self._stats['events_written'],
            backend_type="jsonl",
            oldest_event_ts=self._oldest_ts,
            newest_event_ts=self._newest_ts,
        )

    def query(
        self,
        *,
        event_type: str | None = None,
        agent_id: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit: int = 1000,
    ) -> Iterator:
        """Not supported — raises NotImplementedError."""
        raise NotImplementedError(
            "JSONLBackend does not support query()."
        )
