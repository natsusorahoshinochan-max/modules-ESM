"""Contract tests for the v2-only backend verification command."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

import pytest

import scripts.verify_backend as verify_backend
from scripts.verify_backend import TIERS


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


def test_every_public_tier_has_only_existing_v2_test_targets() -> None:
    assert set(TIERS) == {
        "deterministic-acceptance",
        "examples-v2",
        "fresh-remote-3gb1",
        "installed-biohub-esmc",
        "installed-local-esm3",
        "installed-package",
        "installed-protein-sol",
        "installed-simplefold-confidence",
        "installed-simplefold-folding",
        "installed-soluprot",
        "local-esmfold2-v2-contract",
        "provider-isolation",
        "routine",
        "scientific-repro",
        "security-failure",
    }
    for tier in TIERS.values():
        for argument in tier.pytest_arguments:
            if not argument.startswith("tests/"):
                continue
            target = PROJECT_ROOT / argument.split("::", 1)[0]
            assert target.exists(), argument
    assert not (PROJECT_ROOT / "modules" / "provider_evidence.py").exists()


def test_required_installed_provider_tiers_fail_on_any_skip() -> None:
    assert {
        name
        for name, tier in TIERS.items()
        if tier.zero_skip
    } == {
        "installed-biohub-esmc",
        "installed-local-esm3",
        "installed-protein-sol",
        "installed-simplefold-confidence",
        "installed-simplefold-folding",
        "installed-soluprot",
        "fresh-remote-3gb1",
    }


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
    retained = list(results_root.glob("routine/*/pytest.xml"))
    assert len(retained) == 1
    result_dir = retained[0].parent
    transcript = result_dir / "command-transcript.txt"
    environment_path = result_dir / "environment-summary.json"
    assert "tests=1 failures=0 skipped=0" in transcript.read_text()
    assert "$PROJECT_ENV/bin/python" in transcript.read_text()
    assert stat.S_IMODE(transcript.stat().st_mode) == 0o600
    assert stat.S_IMODE(retained[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(result_dir.stat().st_mode) == 0o700
    environment = json.loads(environment_path.read_text())
    assert environment["schema_version"] == "2.1.0"
    assert environment["historical_cache_allowed"] is False
    assert environment["parallel_provider_evidence_allowed"] is False
    for path in configured_roots.values():
        assert [child.name for child in path.iterdir()] == [
            "production-sentinel"
        ]


def test_verifier_rejects_unsafe_overrides_and_retired_v1_tiers(
    tmp_path: Path,
) -> None:
    unsafe_path = _run_verifier("routine", str(tmp_path / "outside.py"))
    unsafe_option = _run_verifier("routine", "--token=must-not-retain")
    provider_override = _run_verifier(
        "installed-local-esm3",
        "tests/tier_probes/test_isolated_roots.py",
    )
    retired = _run_verifier("live-provider")

    assert unsafe_path.returncode != 0
    assert unsafe_option.returncode != 0
    assert provider_override.returncode != 0
    assert retired.returncode != 0
    assert "repo-relative paths beneath tests/" in unsafe_path.stderr
    assert "must-not-retain" not in unsafe_option.stderr
    assert "do not accept test overrides" in provider_override.stderr
    assert "invalid choice" in retired.stderr


def test_examples_and_scientific_tiers_execute_without_parallel_evidence(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT"] = str(tmp_path)
    env["PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE"] = str(
        tmp_path / "must-not-exist.jsonl"
    )

    examples = _run_verifier("examples-v2", env=env)
    scientific = _run_verifier("scientific-repro", env=env)

    assert examples.returncode == 0, examples.stdout + examples.stderr
    assert scientific.returncode == 0, scientific.stdout + scientific.stderr
    assert "BACKEND VERIFICATION RESULT: passed" in examples.stdout
    assert "BACKEND VERIFICATION RESULT: passed" in scientific.stdout
    assert not (tmp_path / "must-not-exist.jsonl").exists()


def test_output_capture_is_bounded_while_the_pipe_is_fully_drained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify_backend, "MAX_CONSOLE_BYTES", 8)
    captured = bytearray()
    state = {"exceeded": False}

    verify_backend._drain_output(
        io.BytesIO(b"0123456789"),
        captured,
        state,
    )

    assert captured == b"01234567"
    assert state == {"exceeded": True}


def test_verifier_fails_closed_when_console_output_exceeds_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify_backend, "MAX_CONSOLE_BYTES", 1)
    results_root = tmp_path / "verification-results"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT",
        str(results_root),
    )

    result = verify_backend.run(
        "routine",
        ("tests/tier_probes/test_isolated_roots.py",),
    )

    assert result == 1
    transcript = next(
        results_root.glob("routine/*/command-transcript.txt")
    ).read_text()
    assert "console_output_exceeded=true" in transcript


def test_retained_junit_is_size_bounded_and_drops_testcase_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    junit_path = tmp_path / "pytest.xml"
    junit_path.write_text(
        '<testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase classname="/private/source.py" name="contains-secret">'
        "<failure>secret diagnostic</failure>"
        "</testcase>"
        "</testsuite>"
    )

    tests, failures, skipped, retained = (
        verify_backend._bounded_junit_summary(junit_path)
    )

    assert (tests, failures, skipped) == (1, 1, 0)
    assert b"secret" not in retained
    assert b"/private/source.py" not in retained
    monkeypatch.setattr(verify_backend, "MAX_JUNIT_BYTES", 8)
    with pytest.raises(ValueError, match="size bound"):
        verify_backend._bounded_junit_summary(junit_path)


def test_terminate_group_kills_members_after_the_leader_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify_backend,
        "TERMINATION_GRACE_SECONDS",
        0.05,
    )
    leader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys;"
                "child=subprocess.Popen("
                "[sys.executable,'-c',"
                "'import signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "time.sleep(30)'],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                "print(child.pid,flush=True)"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert leader.stdout is not None
    child_pid = int(leader.stdout.readline())
    leader.wait(timeout=5)

    try:
        verify_backend._terminate_group(leader)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = subprocess.run(
                ["/bin/ps", "-o", "stat=", "-p", str(child_pid)],
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
            if not status or status.startswith("Z"):
                break
            time.sleep(0.02)
        assert not status or status.startswith("Z")
    finally:
        try:
            os.kill(child_pid, 9)
        except ProcessLookupError:
            pass
