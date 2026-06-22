# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Sender backends for agent telemetry — SIEM and external webhook delivery."""

try:
    from .exabeam import ExabeamSenderBackend
except (ImportError, RuntimeError):
    ExabeamSenderBackend = None  # Optional: only available with the [exabeam] extra
    __all__ = []
else:
    __all__ = ["ExabeamSenderBackend"]
