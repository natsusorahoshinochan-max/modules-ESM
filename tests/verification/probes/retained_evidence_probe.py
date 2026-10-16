"""Write one provider-free retained Evidence tree for verifier wiring tests."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_retained_evidence_probe() -> None:
    root = Path(
        os.environ["PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_STAGING"]
    )
    _write_json(root / "public-protocol.json", {"protocol": "probe"})
    run_root = root / "runs" / "probe-run"
    _write_json(
        run_root / "projection.json",
        {"outputs": [], "artifact_index": []},
    )
    _write_json(run_root / "events.json", [])
    _write_json(run_root / "typed-values.json", [])
    _write_json(run_root / "artifacts.json", [])
    (run_root / "values").mkdir()
    (run_root / "artifacts").mkdir()
    assert os.environ.get(
        "PROTEIN_WORKBENCH_RETAINED_EVIDENCE_PROBE_FAIL"
    ) != "1"
