"""Tests for aba_telemetry.core.atomic_write."""

import glob
import json
import threading
from pathlib import Path

import pytest

from aba_telemetry.core.atomic_write import (
    atomic_write_json,
    atomic_write_text,
    ConfigWriteError,
)


class TestAtomicWriteJson:

    def test_atomic_write_json_creates_file(self, tmp_path):
        path = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        atomic_write_json(path, data)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_atomic_write_creates_backup(self, tmp_path):
        path = tmp_path / "test.json"
        # Seed with an existing file so a backup is created on overwrite.
        path.write_text(json.dumps({"original": True}), encoding="utf-8")
        atomic_write_json(path, {"new": True})
        pattern = str(tmp_path / "test.bak.*.json")
        backups = [Path(p) for p in glob.glob(pattern)]
        assert len(backups) == 1

    def test_atomic_write_overwrite_creates_new_backup(self, tmp_path):
        path = tmp_path / "test.json"
        # Seed with an existing file.
        path.write_text(json.dumps({"seed": 0}), encoding="utf-8")
        atomic_write_json(path, {"write": 1})
        atomic_write_json(path, {"write": 2})
        pattern = str(tmp_path / "test.bak.*.json")
        backups = [Path(p) for p in glob.glob(pattern)]
        assert len(backups) == 2

    def test_concurrent_writers_produce_valid_json(self, tmp_path):
        path = tmp_path / "test.json"
        barrier = threading.Barrier(10)

        def writer(n):
            barrier.wait(timeout=10)
            atomic_write_json(path, {"writer": n})

        threads = [
            threading.Thread(target=writer, args=(i,))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # At least one writer succeeded; the file must be valid JSON.
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data["writer"], int)
        assert 0 <= data["writer"] <= 9
