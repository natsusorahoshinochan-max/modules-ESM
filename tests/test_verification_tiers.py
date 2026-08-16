"""Contract tests for the v2-only backend verification command."""

from __future__ import annotations

import ast
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
        "fresh-1pga",
        "fresh-2emo",
        "fresh-canonical-3gb1",
        "fresh-5g53",
        "installed-biohub-esm3",
        "installed-biohub-esmc",
        "installed-biohub-esmfold2",
        "installed-local-esmfold2",
        "installed-local-esm3",
        "installed-package",
        "installed-mkdssp",
        "installed-proteinmpnn",
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
    assert (
        "tests/test_installed_backend_v2.py::"
        "test_installed_simplefold_confidence_acceptance_import_closure"
        in TIERS["installed-package"].pytest_arguments
    )
    assert not (PROJECT_ROOT / "modules" / "provider_evidence.py").exists()


def test_proteinmpnn_gate_consumes_the_public_value_retrieval_helper_contract(
) -> None:
    failures: list[str] = []
    for relative_path in (
        "tests/acceptance/test_proteinmpnn_scoring_v2.py",
        "tests/acceptance/test_installed_provider_gates_v2.py",
    ):
        tree = ast.parse((PROJECT_ROOT / relative_path).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_run"
                and isinstance(node.targets[0], ast.Tuple)
                and len(node.targets[0].elts) != 4
            ):
                failures.append(
                    f"{relative_path}:{node.lineno}: _run result arity"
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_decode"
                and len(node.args) != 4
            ):
                failures.append(
                    f"{relative_path}:{node.lineno}: _decode argument arity"
                )
    assert failures == []


def test_required_installed_provider_tiers_fail_on_any_skip() -> None:
    assert {
        name
        for name, tier in TIERS.items()
        if tier.zero_skip
    } == {
        "installed-biohub-esm3",
        "installed-biohub-esmc",
        "installed-biohub-esmfold2",
        "installed-local-esmfold2",
        "installed-local-esm3",
        "installed-mkdssp",
        "installed-proteinmpnn",
        "installed-protein-sol",
        "installed-simplefold-confidence",
        "installed-simplefold-folding",
        "installed-soluprot",
        "fresh-1pga",
        "fresh-2emo",
        "fresh-canonical-3gb1",
        "fresh-5g53",
    }


def test_complete_acceptance_generation_is_exact_and_retains_evidence() -> None:
    from scripts.acceptance_generation import (
        ACCEPTANCE_TIER_ORDER,
        INPUT_DIGESTS,
        INSTALLED_PROVIDER_TIER_ORDER,
        SOURCE_BOUND_TIER_ORDER,
    )

    assert INSTALLED_PROVIDER_TIER_ORDER == (
        "installed-biohub-esmc",
        "installed-biohub-esm3",
        "installed-biohub-esmfold2",
        "installed-local-esm3",
        "installed-local-esmfold2",
        "installed-mkdssp",
        "installed-proteinmpnn",
        "installed-simplefold-folding",
        "installed-simplefold-confidence",
        "installed-soluprot",
        "installed-protein-sol",
    )
    assert SOURCE_BOUND_TIER_ORDER == (
        "fresh-1pga",
        "fresh-2emo",
        "fresh-canonical-3gb1",
        "fresh-5g53",
    )
    assert ACCEPTANCE_TIER_ORDER == (
        *INSTALLED_PROVIDER_TIER_ORDER,
        *SOURCE_BOUND_TIER_ORDER,
    )
    assert INPUT_DIGESTS == {
        "fresh-1pga": (
            "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
        ),
        "fresh-2emo": (
            "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
        ),
        "fresh-canonical-3gb1": (
            "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
        ),
        "fresh-5g53": (
            "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
        ),
    }
    assert all(
        TIERS[name].zero_skip
        and TIERS[name].clean_source
        and TIERS[name].retain_evidence_bundle
        for name in ACCEPTANCE_TIER_ORDER
    )


def test_installed_provider_tiers_select_exact_outer_gates() -> None:
    expected = {
        "installed-biohub-esm3": "test_installed_biohub_esm3_gate",
        "installed-biohub-esmc": "test_installed_biohub_esmc_gate",
        "installed-biohub-esmfold2": "test_installed_biohub_esmfold2_gate",
        "installed-local-esmfold2": "test_installed_local_esmfold2_gate",
        "installed-mkdssp": "test_installed_mkdssp_gate",
        "installed-proteinmpnn": "test_installed_proteinmpnn_gate",
    }

    assert {
        name: tier.pytest_arguments
        for name, tier in TIERS.items()
        if name in expected
    } == {
        name: (
            "tests/test_installed_backend_v2.py::" + outer_gate,
        )
        for name, outer_gate in expected.items()
    }


def test_local_esmfold2_contract_tier_selects_current_translation_test() -> None:
    from tests import test_folding_v2

    target = (
        "tests/test_folding_v2.py::"
        "test_native_plddt_is_statically_scaled_and_projects_protein_tokens"
    )
    assert target in TIERS["local-esmfold2-v2-contract"].pytest_arguments
    assert hasattr(
        test_folding_v2,
        "test_native_plddt_is_statically_scaled_and_projects_protein_tokens",
    )


def test_installed_provider_case_matrix_is_exact_and_collectable() -> None:
    from tests.acceptance.test_installed_provider_gates_v2 import (
        BIOHUB_ESM3_GATE_BINDINGS,
        BIOHUB_ESM3_GATE_INVOCATIONS,
        BIOHUB_ESM3_GATE_VERSION,
    )
    from tests.test_installed_backend_v2 import (
        BIOHUB_ESMC_GATE_VERSION,
        BIOHUB_ESMC_METHOD_VERSION,
        REQUIRED_PROVIDER_CASES,
    )

    assert REQUIRED_PROVIDER_CASES == {
        "biohub_esm3": (
            (
                "tests/acceptance/test_installed_provider_gates_v2.py::"
                "test_biohub_esm3_all_remote_bindings_execute_exact_methods"
            ),
        ),
        "biohub_esmfold2": (
            (
                "tests/acceptance/test_installed_provider_gates_v2.py::"
                "test_biohub_esmfold2_executes_exact_method"
            ),
        ),
        "local_esm3": (
            (
                "tests/acceptance/test_local_esm3.py::"
                "test_local_esm3_all_generation_modes"
            ),
        ),
        "local_esmfold2": (
            (
                "tests/acceptance/test_installed_provider_gates_v2.py::"
                "test_local_esmfold2_executes_exact_method"
            ),
        ),
        "proteinmpnn": (
            (
                "tests/acceptance/test_installed_provider_gates_v2.py::"
                "test_proteinmpnn_design_and_score_execute_exact_methods"
            ),
            (
                "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
                "test_proteinmpnn_v2_scoring_publishes_exact_native_"
                "observation"
            ),
            (
                "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
                "test_proteinmpnn_v2_sibling_design_remains_exact_and_"
                "complete"
            ),
            (
                "tests/acceptance/test_proteinmpnn_chain_order_v2.py::"
                "test_real_proteinmpnn_reversed_axis_design_restores_b_then_a_"
                "layout"
            ),
            (
                "tests/acceptance/test_proteinmpnn_chain_order_v2.py::"
                "test_real_proteinmpnn_preserves_fixed_csh_parent_with_"
                "missing_backbone_atom"
            ),
            (
                "tests/acceptance/test_proteinmpnn_chain_order_v2.py::"
                "test_real_proteinmpnn_scores_signed_insertion_and_gap_axis"
            ),
        ),
        "mkdssp": (
            (
                "tests/acceptance/test_installed_provider_gates_v2.py::"
                "test_mkdssp_executes_exact_method_through_public_run"
            ),
        ),
        "simplefold_folding": (
            (
                "tests/acceptance/test_simplefold_v2.py::"
                "test_simplefold_v2_folds_3gb1_through_exact_binding"
            ),
        ),
        "simplefold_confidence": (
            (
                "tests/acceptance/test_simplefold_confidence_v2.py::"
                "test_simplefold_confidence_v2_evaluates_3gb1_exact_assets_"
                "without_refold"
            ),
        ),
        "soluprot": (
            (
                "tests/acceptance/test_soluprot_v2.py::"
                "test_model_backed_soluprot_golden_methods"
            ),
        ),
        "protein_sol": (
            (
                "tests/acceptance/test_protein_sol_v2.py::"
                "test_local_protein_sol_golden_multiple_metrics"
            ),
        ),
    }
    assert BIOHUB_ESM3_GATE_BINDINGS == (
        "esm3.generate_sequence.biohub_medium",
        "esm3.generate_structure.biohub_medium",
        "esm3.generate_paired.biohub_medium",
        "esm3.generate_sequence.biohub_open",
        "esm3.generate_structure.biohub_open",
        "esm3.generate_paired.biohub_open",
    )
    assert BIOHUB_ESM3_GATE_INVOCATIONS == 8
    assert BIOHUB_ESM3_GATE_VERSION == "7.0.0"
    from core import build_discovered_frozen_catalog

    catalog = build_discovered_frozen_catalog()
    for binding_id in BIOHUB_ESM3_GATE_BINDINGS:
        binding = catalog.require_contract(
            "binding",
            binding_id,
            BIOHUB_ESM3_GATE_VERSION,
        )
        assert binding.descriptor["node_type"]["contract_version"] == (
            BIOHUB_ESM3_GATE_VERSION
        )
    esmc_binding = catalog.require_contract(
        "binding",
        "esm3.represent_sequence.biohub_esmc_600m_2024_12",
        BIOHUB_ESMC_GATE_VERSION,
    )
    assert esmc_binding.descriptor["node_type"]["contract_version"] == (
        BIOHUB_ESMC_GATE_VERSION
    )
    assert esmc_binding.descriptor["method"]["contract_version"] == (
        BIOHUB_ESMC_METHOD_VERSION
    )
    assert all(
        selector.startswith("tests/")
        and (PROJECT_ROOT / selector.split("::", 1)[0]).is_file()
        for selectors in REQUIRED_PROVIDER_CASES.values()
        for selector in selectors
    )
    selectors = tuple(
        selector
        for case_selectors in REQUIRED_PROVIDER_CASES.values()
        for selector in case_selectors
    )
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "--collect-only",
            "-q",
            *selectors,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert all(
        selector in collected.stdout
        for selector in selectors
    )


def test_solubility_gates_require_explicit_trusted_runtime_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.acceptance.test_protein_sol_v2 import _trusted_source_root
    from tests.acceptance.test_soluprot_v2 import _trusted_external_root

    monkeypatch.delenv("PROTEIN_WORKBENCH_SOLUPROT_ROOT", raising=False)
    monkeypatch.delenv("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT", raising=False)
    with pytest.raises(AssertionError, match="SOLUPROT_ROOT"):
        _trusted_external_root()
    with pytest.raises(AssertionError, match="PROTEIN_SOL_ROOT"):
        _trusted_source_root()

    monkeypatch.setenv("PROTEIN_WORKBENCH_SOLUPROT_ROOT", "relative")
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT", "relative")
    with pytest.raises(AssertionError):
        _trusted_external_root()
    with pytest.raises(AssertionError):
        _trusted_source_root()

    soluprot_root = tmp_path / "soluprot"
    protein_sol_root = tmp_path / "protein-sol"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SOLUPROT_ROOT",
        str(soluprot_root),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",
        str(protein_sol_root),
    )
    assert _trusted_external_root() == soluprot_root.resolve()
    assert _trusted_source_root() == protein_sol_root.resolve()


def test_installed_gate_paths_are_explicit_and_token_checks_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.acceptance.test_installed_provider_gates_v2 import (
        _required_absolute_path,
    )

    variable = "PROTEIN_WORKBENCH_TEST_PROVIDER_ROOT"
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(AssertionError, match="must be configured"):
        _required_absolute_path(variable)
    monkeypatch.setenv(variable, "relative")
    with pytest.raises(AssertionError, match="absolute path"):
        _required_absolute_path(variable)
    configured = tmp_path / "provider"
    monkeypatch.setenv(variable, str(configured))
    assert _required_absolute_path(variable) == configured.resolve()

    sources = "\n".join(
        path.read_text()
        for path in (
            PROJECT_ROOT / "tests/acceptance/test_installed_provider_gates_v2.py",
            PROJECT_ROOT / "tests/test_installed_backend_v2.py",
            PROJECT_ROOT / "tests/acceptance/test_soluprot_v2.py",
            PROJECT_ROOT / "tests/acceptance/test_protein_sol_v2.py",
        )
    )
    assert "/Users/" not in sources
    assert "assert credential_handle" not in sources


def test_mkdssp_gate_catalog_closure_is_buildable() -> None:
    from core import build_frozen_catalog
    from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.structure_annotation.package import (
        MODULE_PACKAGE as STRUCTURE_ANNOTATION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            PROTEIN_IO_PACKAGE,
            PROMPT_AUTHORING_PACKAGE,
            STRUCTURE_ANNOTATION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    binding = catalog.require_contract(
        "binding",
        "structure_annotation.dssp_compute.mkdssp_local",
        "6.0.0",
    )
    method = binding.descriptor["method"]
    assert catalog.require_contract(
        "method",
        method["contract_id"],
        method["contract_version"],
    ).contract_digest == method["contract_digest"]


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
    env["PYTEST_ADDOPTS"] = "--this-option-must-not-reach-pytest"

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
