"""Slow public verifier probe selected only by interruption tests."""

from __future__ import annotations

import os
from pathlib import Path
import time


def test_wait_for_verifier_interruption() -> None:
    Path(os.environ["PROTEIN_WORKBENCH_INTERRUPT_PROBE_PID"]).write_text(
        str(os.getpid()),
        encoding="utf-8",
    )
    time.sleep(60)
