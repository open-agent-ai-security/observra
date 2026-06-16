"""Utility functions for observra."""

import logging
import time
from ulid import ULID

logger = logging.getLogger(__name__)


def generate_ulid() -> str:
    """Generate a ULID string.

    Returns:
        26-character ULID string
    """
    return str(ULID())


def generate_timestamp() -> float:
    """Generate current timestamp.

    Returns:
        Unix timestamp as float
    """
    return time.time()
