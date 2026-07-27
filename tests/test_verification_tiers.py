"""Contract tests for the public backend verification commands."""

from __future__ import annotations

import os
import json
import select
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
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


def _start_process_supervisor(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen[str], int, object]:
    control_read, control_write = os.pipe()
    status_read, status_write = os.pipe()
    process = subprocess.Popen(
        [
            sys.executable,
            str(VERIFY_COMMAND),
            "--verification-process-supervisor",
            str(control_read),
            str(status_write),
            *command,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        pass_fds=(control_read, status_write),
    )
    os.close(control_read)
    os.close(status_write)
    status_file = os.fdopen(status_read, "rb")
    assert status_file.readline() == b"READY\n"
    return process, control_write, status_file


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
    transcript = retained_results[0].parent / "command-transcript.txt"
    assert transcript.exists()
    assert "tests/tier_probes/test_isolated_roots.py" in transcript.read_text()
    assert "return_code=0" in transcript.read_text()
    assert "tests=1 failures=0 skipped=0" in transcript.read_text()
    assert "$PROJECT_ENV/bin/python" in transcript.read_text()
    assert str(PROJECT_ROOT) not in transcript.read_text()
    assert stat.S_IMODE(transcript.stat().st_mode) == 0o600
    assert stat.S_IMODE(retained_results[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(retained_results[0].parent.stat().st_mode) == 0o700
    environment = json.loads(
        (retained_results[0].parent / "environment-summary.json").read_text()
    )
    assert environment["interpreter"] == str(Path(sys.executable).resolve())
    assert len(environment["interpreter_sha256"]) == 64
    unsafe_path = _run_verifier("routine", str(tmp_path / "outside.py"))
    unsafe_secret = _run_verifier("routine", "--token=must-not-retain")
    unsafe_absolute_selector = _run_verifier(
        "routine",
        "tests/test_server.py::/private/sensitive/absolute-path",
    )
    unsafe_parent_selector = _run_verifier(
        "routine",
        "tests/test_server.py::../../sensitive-path",
    )
    assert unsafe_path.returncode != 0
    assert unsafe_secret.returncode != 0
    assert unsafe_absolute_selector.returncode != 0
    assert unsafe_parent_selector.returncode != 0
    assert "repo-relative paths beneath tests/" in unsafe_path.stderr
    assert "must-not-retain" not in unsafe_secret.stderr
    assert "/private/sensitive/absolute-path" not in unsafe_absolute_selector.stderr
    assert "../../sensitive-path" not in unsafe_parent_selector.stderr
    for path in configured_roots.values():
        assert [child.name for child in path.iterdir()] == ["production-sentinel"]
        assert (path / "production-sentinel").read_text() == "unchanged"
    warning_env = env.copy()
    warning_env["PROTEIN_WORKBENCH_RESOURCE_WARNING_PROBE"] = "1"
    warning_result = _run_verifier(
        "routine",
        "tests/tier_probes/test_isolated_roots.py",
        env=warning_env,
    )
    assert warning_result.returncode != 0
    assert "BACKEND VERIFICATION RESULT: failed" in warning_result.stdout
    assert (
        "multiprocessing resource cleanup warning"
        in warning_result.stdout
    )


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


def test_live_provider_tier_rejects_forged_provider_evidence() -> None:
    result = _run_verifier(
        "live-provider",
        "tests/tier_probes/test_live_gate_contract.py::"
        "test_forged_provider_evidence_probe",
    )

    assert result.returncode != 0
    assert "BACKEND VERIFICATION RESULT: incomplete" in result.stdout
    assert "invalid provider-call evidence" in result.stdout


def test_live_provider_tier_rejects_call_without_readiness() -> None:
    result = _run_verifier(
        "live-provider",
        "tests/tier_probes/test_live_gate_contract.py::"
        "test_call_without_readiness_probe",
    )

    assert result.returncode != 0
    assert "BACKEND VERIFICATION RESULT: incomplete" in result.stdout
    assert "provider call test identity mismatch" in result.stdout


def test_focused_provider_diagnostics_cannot_satisfy_full_gate() -> None:
    result = _run_verifier(
        "live-provider",
        "tests/tier_probes/test_live_gate_contract.py::"
        "test_self_reported_call_and_readiness_probe",
    )

    assert result.returncode != 0
    assert "BACKEND VERIFICATION RESULT: incomplete" in result.stdout
    assert "provider call test identity mismatch" in result.stdout


def test_provider_summary_completion_requires_overall_full_gate_success() -> None:
    from scripts.verify_backend import _provider_summary_completion

    passing = {
        "evidence_error": None,
        "focused": False,
        "return_code": 0,
        "failures": 0,
        "skipped": 0,
        "tests": 5,
        "resource_cleanup_warning": False,
        "source_attestation_valid": True,
    }

    assert _provider_summary_completion(**passing) == (True, None)
    assert _provider_summary_completion(
        **{**passing, "focused": True}
    ) == (False, "focused provider diagnostic")
    assert _provider_summary_completion(
        **{**passing, "return_code": 1, "failures": 1}
    ) == (False, "provider pytest failed")
    assert _provider_summary_completion(
        **{**passing, "source_attestation_valid": False}
    ) == (False, "source attestation changed during provider execution")


def test_full_provider_gate_rejects_one_missing_required_call(
    tmp_path: Path,
) -> None:
    from core.provider_contract import ESM_SDK_REVISION
    from scripts.verify_backend import (
        TIERS,
        validate_provider_evidence,
    )

    started_at = datetime.now(timezone.utc)
    identity = {
        "sdk": "esm",
        "sdk_source_revision": ESM_SDK_REVISION,
        "service": "Biohub",
    }
    common = {
        "evidence_version": 1,
        "run_nonce": "nonce",
        "gate": "live-provider",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    events = [
        {
            **common,
            "event_id": "readiness",
            "test_id": (
                "tests/acceptance/test_biohub_generation.py::"
                "TestBiohubGeneration::test_generate_3gb1_sequence"
            ),
            "event_type": "provider_readiness",
            "provider": "biohub",
            "ready": True,
            "provider_identity": identity,
            "details": {"credential_present": True},
        },
        {
            **common,
            "event_id": "call",
            "test_id": (
                "tests/acceptance/test_biohub_generation.py::"
                "TestBiohubGeneration::test_generate_3gb1_sequence"
            ),
            "event_type": "provider_call",
            "provider": "biohub",
            "operation": "esm3.generate_sequence",
            "model": "esm3-medium-2024-08",
            "provider_identity": identity,
            "readiness": "ready_at_call_boundary",
            "actual_call": True,
            "call_count": 1,
            "effective_seed": None,
            "seed_control": "unsupported_by_provider",
            "cache_decision": "bypassed_fresh_direct_call",
            "result": {
                "status": "succeeded",
                "summary": {"result_type": "ESMProtein"},
            },
        },
    ]
    evidence_path = tmp_path / "provider-calls.jsonl"
    evidence_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )

    _, error = validate_provider_evidence(
        evidence_path,
        tier_name="live-provider",
        tier=TIERS["live-provider"],
        nonce="nonce",
        started_at=started_at,
        focused=False,
    )

    assert error == "missing required provider calls: biohub:esmfold2.fold"


def test_fresh_remote_gate_requires_exact_repeated_provider_calls(
    tmp_path: Path,
) -> None:
    from core.provider_contract import esm_provider_identity
    from scripts.verify_backend import (
        TIERS,
        validate_provider_evidence,
    )

    tier = TIERS["fresh-remote-3gb1"]
    started_at = datetime.now(timezone.utc)
    common = {
        "evidence_version": 1,
        "run_nonce": "nonce",
        "gate": "fresh-remote-3gb1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "test_id": (
            "tests/fresh_remote_acceptance/test_fresh_remote_3gb1.py::"
            "test_fresh_remote_real_canonical_3gb1"
        ),
    }
    local_identity = esm_provider_identity(local=True)
    events = [{
        **common,
        "event_id": "readiness",
        "event_type": "provider_readiness",
        "provider": "local_open",
        "ready": True,
        "provider_identity": local_identity,
        "details": {"snapshot_validated": True},
    }]
    for index in range(9):
        events.append({
            **common,
            "event_id": f"call-{index}",
            "event_type": "provider_call",
            "provider": "local_open",
            "operation": "esm3.generate_sequence",
            "model": "esm3_sm_open_v1",
            "provider_identity": local_identity,
            "readiness": "ready_at_call_boundary",
            "actual_call": True,
            "call_count": 1,
            "effective_seed": index,
            "seed_control": "torch_local",
            "cache_decision": "bypassed_fresh_direct_call",
            "result": {
                "status": "succeeded",
                "summary": {"result_type": "ESMProtein"},
            },
        })
    evidence_path = tmp_path / "provider-calls.jsonl"
    evidence_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )

    _, error = validate_provider_evidence(
        evidence_path,
        tier_name="fresh-remote-3gb1",
        tier=tier,
        nonce="nonce",
        started_at=started_at,
        focused=False,
    )

    assert error == (
        "provider call count mismatch: "
        "local_open:esm3.generate_sequence expected 10, observed 9"
    )


def test_fresh_remote_bundle_validation_fails_closed_on_missing_seal(
    tmp_path: Path,
) -> None:
    from scripts.verify_backend import validate_fresh_bundle

    run_id, error = validate_fresh_bundle(
        tmp_path,
        expected_revision="1" * 40,
        provider_events=[],
    )

    assert run_id is None
    assert error == "sealed manifest was not a bounded regular file"


def test_process_supervisor_cleans_lingering_group_member() -> None:
    process, control_write, status_file = _start_process_supervisor(
        [
            sys.executable,
            "-c",
            (
                "import subprocess;"
                "child=subprocess.Popen(['/bin/sleep','30']);"
                "print(child.pid,flush=True)"
            ),
        ]
    )
    assert process.stdout is not None
    lingering_pid = int(process.stdout.readline())
    assert process.stdout.read() == ""
    assert status_file.readline() == b"DONE:0\n"
    os.write(control_write, b"R")
    os.close(control_write)
    status_file.close()
    assert process.wait(timeout=5) == 0
    try:
        os.kill(lingering_pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("supervisor left a process-group member alive")


def test_process_supervisor_retains_group_leader_until_escalation() -> None:
    process, control_write, status_file = _start_process_supervisor(
        ["/bin/sleep", "30"]
    )
    try:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise AssertionError("supervisor released its PGID before escalation")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        os.close(control_write)
        status_file.close()


def test_verifier_timeout_retains_then_cleans_supervisor_group() -> None:
    env = os.environ.copy()
    env["PROTEIN_WORKBENCH_PROCESS_TIMEOUT_PROBE"] = "1"
    started_at = time.monotonic()
    process = subprocess.Popen(
        [
            sys.executable,
            str(VERIFY_COMMAND),
            "routine",
            "--",
            "tests/tier_probes/process_timeout_probe.py",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    supervisor_pid: int | None = None
    try:
        discovery_deadline = time.monotonic() + 3
        while time.monotonic() < discovery_deadline:
            completed = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,command="],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in completed.stdout.splitlines():
                fields = line.split(maxsplit=2)
                if len(fields) != 3:
                    continue
                pid_text, parent_text, command = fields
                if (
                    int(parent_text) == process.pid
                    and "--verification-process-supervisor" in command
                ):
                    supervisor_pid = int(pid_text)
                    break
            if supervisor_pid is not None:
                break
            time.sleep(0.02)
        assert supervisor_pid is not None
        assert os.getpgid(supervisor_pid) == supervisor_pid

        assert process.stdout is not None
        observed_output: list[str] = []
        marker = "PROCESS TIMEOUT PROBE: timeout acquired"
        marker_deadline = started_at + 5
        marker_at: float | None = None
        while time.monotonic() < marker_deadline:
            readable, _, _ = select.select(
                [process.stdout],
                [],
                [],
                marker_deadline - time.monotonic(),
            )
            assert readable
            line = process.stdout.readline()
            assert line
            observed_output.append(line)
            if marker in line:
                marker_at = time.monotonic()
                break
        assert marker_at is not None

        short_watchdog_deadline = marker_at + 5.5
        while time.monotonic() < short_watchdog_deadline:
            assert process.poll() is None
            time.sleep(0.05)
        os.kill(supervisor_pid, 0)

        stdout, _ = process.communicate(timeout=10)
        stdout = "".join(observed_output) + stdout
        assert process.returncode != 0
        assert "BACKEND VERIFICATION RESULT: failed" in stdout
        assert "tier timeout" in stdout
        try:
            os.killpg(supervisor_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("timeout path left its process group alive")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if supervisor_pid is not None:
            try:
                os.killpg(supervisor_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_process_supervisor_cleans_group_when_parent_disappears() -> None:
    process, control_write, status_file = _start_process_supervisor(
        ["/bin/sleep", "30"]
    )

    os.close(control_write)
    status_file.close()

    assert process.wait(timeout=10) < 0


def test_process_supervisor_fails_closed_when_group_enumeration_fails() -> None:
    env = os.environ.copy()
    env["PATH"] = "/path-that-does-not-contain-ps"
    process, control_write, status_file = _start_process_supervisor(
        [
            sys.executable,
            "-c",
            (
                "import subprocess;"
                "child=subprocess.Popen(['/bin/sleep','30']);"
                "print(child.pid,flush=True)"
            ),
        ],
        env=env,
    )
    assert process.stdout is not None
    lingering_pid = int(process.stdout.readline())

    assert status_file.readline() == b""
    assert process.wait(timeout=10) < 0
    os.close(control_write)
    status_file.close()
    try:
        os.kill(lingering_pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError(
            "supervisor enumeration failure left a process-group member alive"
        )


def test_scientific_reproduction_tier_confirms_sci_001_repair() -> None:
    result = _run_verifier("scientific-repro")

    assert result.returncode == 0
    assert "BACKEND VERIFICATION TIER: scientific-repro" in result.stdout
    assert "BACKEND VERIFICATION RESULT: passed" in result.stdout
