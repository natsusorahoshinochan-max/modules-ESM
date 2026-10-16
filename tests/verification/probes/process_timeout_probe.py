"""Fast probe used to synchronize a public verifier timeout after DONE."""

from __future__ import annotations

import os


def test_process_timeout_probe_reaches_done() -> None:
    assert os.environ.get("PROTEIN_WORKBENCH_PROCESS_TIMEOUT_PROBE") == "1"
