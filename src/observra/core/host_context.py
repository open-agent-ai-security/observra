# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Host identity (hostname + login user + os + arch + device id + lib version).

Read once at first access via stdlib calls, then reused
for every event by ``create_event``. Mirrors ``rust/src/host_context.rs``
so events emitted by the Python SDK and the Rust forwarder carry the same
host attribution shape.

The one subprocess is ``/usr/sbin/ioreg`` on macOS, which has no stdlib way to
read the hardware UUID; it runs once per process.

Failures are tolerated — fields stay ``None`` rather than crashing the
agent, since a missing host attribution is preferable to a dead instrumented
process.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import platform
import socket
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True, slots=True)
class HostContext:
    host: Optional[str]
    user: Optional[str]
    os: Optional[str]
    arch: Optional[str]
    library_version: str
    device_id: Optional[str] = None


def _read_hostname() -> Optional[str]:
    try:
        h = socket.gethostname()
        return h or None
    except Exception:
        return None


def _read_user() -> Optional[str]:
    try:
        u = getpass.getuser()
        return u or None
    except Exception:
        # Fall back to env vars if getpass fails (e.g. no /etc/passwd entry).
        for var in ("USER", "USERNAME", "LOGNAME"):
            v = os.environ.get(var)
            if v:
                return v
        return None


def _read_os() -> Optional[str]:
    try:
        # ``platform.platform()`` returns something like "macOS-14.5-arm64-arm-64bit".
        # We prefer a friendlier shape for Linux/macOS/Windows; fall back on platform.platform().
        system = platform.system()
        if system == "Darwin":
            ver = platform.mac_ver()[0] or ""
            return f"macOS {ver}".strip() if ver else "macOS"
        if system == "Linux":
            # /etc/os-release PRETTY_NAME is the most informative; fall back to uname.
            try:
                with open("/etc/os-release", encoding="utf-8") as fh:
                    for line in fh:
                        if line.startswith("PRETTY_NAME="):
                            return line.split("=", 1)[1].strip().strip('"')
            except OSError:
                pass
            return f"Linux {platform.release()}".strip()
        if system == "Windows":
            return f"Windows {platform.release()}".strip()
        if system:
            return system
        return platform.platform()
    except Exception:
        return None


def _read_arch() -> Optional[str]:
    """Return the machine architecture, normalized to match the Rust forwarder.

    macOS reports ``arm64`` via uname but Rust ``std::env::consts::ARCH`` reports
    ``aarch64``. We normalize so SIEM groupings on ``arch`` see the same value
    regardless of which runtime emitted the event.
    """
    try:
        m = platform.machine()
        if not m:
            return None
        # Map common platform.machine() values to Rust's std::env::consts::ARCH.
        norm = {
            "arm64": "aarch64",
            "amd64": "x86_64",
            "i686": "x86",
            "i386": "x86",
        }.get(m.lower(), m.lower())
        return norm
    except Exception:
        return None


def _read_machine_id() -> Optional[str]:
    """Return the OS-assigned machine identifier, or None."""
    system = platform.system()
    if system == "Linux":
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(path, encoding="utf-8") as fh:
                    value = fh.read().strip()
                if value:
                    return value
            except OSError:
                continue
        return None
    if system == "Darwin":
        out = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout
        for line in out.splitlines():
            if '"IOPlatformUUID"' in line:
                return line.split("=", 1)[1].strip().strip('"') or None
        return None
    if system == "Windows":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0]) or None
    return None


def _read_device_id() -> Optional[str]:
    """Return SHA-256 (hex) of the machine id.

    Stable across hostname changes, unlike ``host``. Hashed because the raw
    machine id is meant to stay on the machine (machine-id(5)); a plain,
    unkeyed hash lets agent-sensor compute the same value for correlation.
    """
    try:
        raw = _read_machine_id()
    except Exception:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None


def _read_library_version() -> str:
    # Avoid importing the parent package at module-import time to prevent
    # circular imports. Use ``importlib.metadata`` when the package is
    # installed; otherwise fall back to the in-tree __version__.
    try:
        from importlib.metadata import version

        return version("observra")
    except Exception:
        try:
            from observra import __version__

            return __version__
        except Exception:
            return "unknown"


@lru_cache(maxsize=1)
def get_host_context() -> HostContext:
    """Return the cached host context, computing it on first call."""
    return HostContext(
        host=_read_hostname(),
        user=_read_user(),
        os=_read_os(),
        arch=_read_arch(),
        library_version=_read_library_version(),
        device_id=_read_device_id(),
    )
