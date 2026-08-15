"""Safe process-group signaling shared by worker and provider boundaries."""

from __future__ import annotations

from collections.abc import Callable
import os
import signal


def verification_uses_shared_process_group() -> bool:
    """Keep the fresh gate in its supervisor-owned process group."""
    return (
        os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER")
        in {
            "fresh-1pga",
            "fresh-2emo",
            "fresh-canonical-3gb1",
            "fresh-5g53",
        }
        and os.environ.get("PROTEIN_WORKBENCH_PROCESS_CONTAINMENT")
        == "shared_process_group"
    )


def enter_module_worker_process_group() -> bool:
    """Isolate normal workers; keep fresh-gate workers supervisor-owned."""
    if verification_uses_shared_process_group():
        return False
    os.setsid()
    return True


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
