"""Contract tests for the public backend verification commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
VERIFY_COMMAND = PROJECT_ROOT / "scripts" / "verify_backend.py"
ROOT_VARIABLES = (
    "PROTEIN_WORKBENCH_PROJECT_ROOT",
    "PROTEIN_WORKBENCH_CACHE_ROOT",
    "PROTEIN_WORKBENCH_OUTPUT_ROOT",
    "PROTEIN_WORKBENCH_RUN_ROOT",
)


def _run_verifier(
    tier: str,
    *pytest_targets: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VERIFY_COMMAND), tier]
    if pytest_targets:
        command.extend(["--", *pytest_targets])
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_routine_tier_reports_result_and_preserves_configured_roots(
    tmp_path: Path,
) -> None:
    configured_roots = {
        variable: tmp_path / variable.lower()
        for variable in ROOT_VARIABLES
    }
    for path in configured_roots.values():
        path.mkdir()
        (path / "production-sentinel").write_text("unchanged")

    env = os.environ.copy()
    env.update({name: str(path) for name, path in configured_roots.items()})
    results_root = tmp_path / "verification-results"
    env["PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT"] = str(results_root)
    result = _run_verifier(
        "routine",
        "tests/tier_probes/test_isolated_roots.py",
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BACKEND VERIFICATION TIER: routine" in result.stdout
    assert "BACKEND VERIFICATION RESULT: passed" in result.stdout
    retained_results = list(results_root.glob("routine/*/pytest.xml"))
    assert len(retained_results) == 1
    assert str(retained_results[0].parent) in result.stdout
    for path in configured_roots.values():
        assert [child.name for child in path.iterdir()] == ["production-sentinel"]
        assert (path / "production-sentinel").read_text() == "unchanged"


def test_live_provider_tier_rejects_a_skipped_test() -> None:
    result = _run_verifier(
        "live-provider",
        "tests/tier_probes/test_live_gate_contract.py::test_skipped_provider_probe",
    )

    assert result.returncode != 0
    assert "BACKEND VERIFICATION TIER: live-provider" in result.stdout
    assert "BACKEND VERIFICATION RESULT: incomplete" in result.stdout
    assert "skipped test" in result.stdout


def test_live_provider_tier_rejects_readiness_without_call_evidence() -> None:
    result = _run_verifier(
        "live-provider",
        "tests/tier_probes/test_live_gate_contract.py::test_readiness_only_probe",
    )

    assert result.returncode != 0
    assert "BACKEND VERIFICATION RESULT: incomplete" in result.stdout
    assert "provider-call evidence" in result.stdout


def test_scientific_reproduction_tier_confirms_sci_001_repair() -> None:
    result = _run_verifier("scientific-repro")

    assert result.returncode == 0
    assert "BACKEND VERIFICATION TIER: scientific-repro" in result.stdout
    assert "BACKEND VERIFICATION RESULT: passed" in result.stdout
