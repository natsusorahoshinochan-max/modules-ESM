"""Safe process-group signaling shared by worker and provider boundaries."""

from __future__ import annotations

from collections.abc import Callable
import os
import signal


def signal_process_group(
    process_group: int,
    process_signal: signal.Signals,
    *,
    fallback: Callable[[], None] | None = None,
) -> None:
    """Signal an isolated process group without risking the backend's group."""
    try:
        if process_group <= 1 or process_group == os.getpgrp():
            raise PermissionError
        os.killpg(process_group, process_signal)
    except (ProcessLookupError, PermissionError, OSError):
        if fallback is not None:
            fallback()
