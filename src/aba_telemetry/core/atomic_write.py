"""Atomic file writes with backup, fsync, and validation for config files.

Provides atomic write primitives for JSON and text config files,
eliminating the truncation/corruption hazard when concurrent writes
or crashes occur mid-write.

Usage::

    from aba_telemetry.core.atomic_write import atomic_write_json, atomic_write_text

    atomic_write_json(Path("~/.claude/settings.json"), {"hooks": {}})
    atomic_write_text(Path("~/.codex/config.toml"), "[features]\ncodex_hooks = true\n")
"""

from __future__ import annotations

import glob
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ConfigWriteError(Exception):
    """Raised when an atomic write fails and backup restoration also fails.

    Attributes:
        message: Human-readable description of what went wrong.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _backup_path(path: Path) -> Path:
    """Generate a timestamped backup path.

    Format: ``{stem}.bak.{timestamp}{ext}`` where timestamp is millisecond-precision
    UTC ISO-8601 (e.g. ``settings.bak.20260428T153045.123Z.json``).

    Args:
        path: Original file path.

    Returns:
        Absolute backup path ready for ``shutil.copy2``.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:23] + "Z"
    return path.with_name(f"{path.stem}.bak.{ts}{path.suffix}")


def _find_latest_backup(path: Path) -> Optional[Path]:
    """Return the most recently created backup for *path*, if any.

    Args:
        path: Original file path.

    Returns:
        Path to the newest backup, or ``None`` if no backups match.
    """
    pattern = str(path.parent / f"{path.stem}.bak.*{path.suffix}")
    backups = [Path(p) for p in glob.glob(pattern)]
    if not backups:
        return None
    # Prefer ctime then mtime; on systems without ctime fall back to mtime.
    def _sort_key(p: Path):
        st = p.stat()
        return (st.st_ctime, st.st_mtime)
    backups.sort(key=_sort_key, reverse=True)
    return backups[0]


def _write_atomic(path: Path, content: str) -> None:
    """Core atomic write: write to a temp file, fsync, then rename.

    Creates a timestamped backup before overwriting an existing file.
    Uses ``os.replace`` (POSIX) / ``os.rename`` (Windows) for the final
    atomic rename.

    Args:
        path: Target file path.
        content: UTF-8 text content to write.

    Raises:
        ConfigWriteError: If the write or rename fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    # Preserve existing file as a backup before we overwrite it.
    if path.exists():
        backup = _backup_path(path)
        try:
            shutil.copy2(str(path), str(backup))
        except OSError as exc:
            raise ConfigWriteError(
                f"Failed to create backup {backup} for {path}: {exc}"
            ) from exc

    # Write to temp, fsync for durability, then close before rename.
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ConfigWriteError(f"Failed to write temp file {tmp}: {exc}") from exc
    finally:
        os.close(fd)

    # Atomic rename — temp becomes the live file.
    try:
        os.replace(str(tmp), str(path))
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ConfigWriteError(f"Failed to rename {tmp} -> {path}: {exc}") from exc

    # Optional: fsync parent directory on POSIX so the directory entry is durable.
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass  # Windows or restricted env — not critical


def _restore_backup(path: Path) -> bool:
    """Restore *path* from its most recent backup, if available.

    Args:
        path: File to restore.

    Returns:
        ``True`` if a backup was found and restored.
    """
    backup = _find_latest_backup(path)
    if backup is None or not backup.exists():
        return False
    shutil.copy2(str(backup), str(path))
    return True


def atomic_write_json(path: Path, data: dict) -> None:
    """Atomically write *data* as indented JSON to *path* with validation.

    Steps:
    1. Serialize *data* to JSON with ``indent=2``.
    2. Call :func:`_write_atomic` to write with backup + fsync + rename.
    3. Re-read the file and ``json.loads`` it to validate correctness.
    4. If validation fails, restore from the most recent backup and raise
       :class:`ConfigWriteError`.

    This prevents corruption from crashes, power loss, or race conditions
    between write and read.

    Args:
        path: Target JSON file path.
        data: Dictionary to serialize.

    Raises:
        ConfigWriteError: If write or validation fails.
    """
    content = json.dumps(data, indent=2)
    _write_atomic(path, content)

    # Re-read and validate.
    try:
        loaded_text = path.read_text(encoding="utf-8")
        loaded = json.loads(loaded_text)
    except (json.JSONDecodeError, OSError) as exc:
        if _restore_backup(path):
            raise ConfigWriteError(
                f"Validation failed for {path}; restored from backup: {exc}"
            ) from exc
        raise ConfigWriteError(f"Validation failed for {path}: {exc}") from exc

    if loaded != data:
        if _restore_backup(path):
            raise ConfigWriteError(
                f"Validation failed for {path}: round-trip mismatch; restored from backup"
            )
        raise ConfigWriteError(f"Validation failed for {path}: round-trip mismatch")


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically write *text* to *path* with round-trip validation.

    Uses the same backup + fsync + rename guarantees as :func:`atomic_write_json`.

    Args:
        path: Target file path.
        text: UTF-8 text content.

    Raises:
        ConfigWriteError: If write or round-trip fails.
    """
    _write_atomic(path, text)

    try:
        read_back = path.read_text(encoding="utf-8")
    except OSError as exc:
        if _restore_backup(path):
            raise ConfigWriteError(
                f"Validation failed for {path}; restored from backup: {exc}"
            ) from exc
        raise ConfigWriteError(f"Validation failed for {path}: {exc}") from exc

    if read_back != text:
        if _restore_backup(path):
            raise ConfigWriteError(
                f"Validation failed for {path}: round-trip mismatch; restored from backup"
            )
        raise ConfigWriteError(f"Validation failed for {path}: round-trip mismatch")
