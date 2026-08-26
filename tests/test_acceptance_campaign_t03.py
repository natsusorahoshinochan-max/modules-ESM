"""T03 contracts for the Acceptance Campaign execution authority."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

import verification.backend as verify_backend
from protein_workbench_public.workflow_codec import decode_workflow_document
from verification.acceptance_campaign import (
    CAMPAIGN_SCHEMA_NAMESPACE,
    CAMPAIGN_DEFINITION_SCHEMA_NAMESPACE,
    CANONICAL_ACCEPTANCE_TIERS,
    PROFILE_SCHEMA_NAMESPACE,
    ExecutionProfile,
    TierExecutionOutcome,
    acceptance_definition,
    acceptance_tier,
    campaign_status,
    prepare_campaign,
    run_campaign,
    write_tier_execution_outcome,
)


def _write_profile(tmp_path: Path) -> Path:
    configured = tmp_path / "configured"
    configured.mkdir(parents=True)
    names = {
        name
        for tier in CANONICAL_ACCEPTANCE_TIERS
        for alternatives in tier.environment_configuration
        for name in alternatives
    }
    path = tmp_path / "acceptance-profile.json"
    path.write_text(
        json.dumps({
            "schema_namespace": PROFILE_SCHEMA_NAMESPACE,
            "provider_configuration": {
                name: str(configured)
                for name in sorted(names)
            },
            "remote_transport": {"proxy_policy": "direct"},
        }),
        encoding="utf-8",
    )
    return path


def _prepared_campaign(
    root: Path,
    profile: ExecutionProfile,
) -> dict[str, object]:
    (root / "artifacts").mkdir(parents=True)
    (root / "artifacts" / "protein_workbench.whl").write_bytes(b"wheel")
    (root / "artifacts" / "protein_workbench.tar.gz").write_bytes(b"sdist")
    manifest: dict[str, object] = {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "source_revision": "a" * 40,
        "candidate": {
            "wheel": {
                "path": "artifacts/protein_workbench.whl",
                "sha256": (
                    "ba59926159d2aa256eb8739b8da7e2b574b960e1202c6d624cbe981cef996c91"
                ),
            },
            "sdist": {
                "path": "artifacts/protein_workbench.tar.gz",
                "sha256": (
                    "714772a9f82b2aeb4fa5f7092d00fe4ac4c9cdeb6800840b6ed39ea64c4d785a"
                ),
            },
        },
        "definition": acceptance_definition(),
        "execution_profile": profile.public_definition(),
        "state": "prepared",
        "executions": [],
    }
    (root / "campaign.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return manifest


def _outcome(
    root: Path,
    tier_name: str,
    conclusion: str,
) -> TierExecutionOutcome:
    tier = acceptance_tier(tier_name)
    retained_relative = Path(tier_name) / conclusion
    retained_root = root / "results" / retained_relative
    evidence_root = retained_root / "evidence"
    for run_label in tier.required_run_labels:
        (evidence_root / "runs" / run_label).mkdir(parents=True)
    if tier.lifecycle_receipt_required:
        (evidence_root / "model-lifecycle.json").write_text("{}\n")
    (retained_root / "pytest.xml").write_text("<testsuite/>\n")
    for diagnostic in ("command-transcript.txt", "console-output.txt"):
        (retained_root / diagnostic).write_text("diagnostic\n")
    return TierExecutionOutcome(
        tier=tier_name,
        source_revision="a" * 40,
        retained_location=retained_relative.as_posix(),
        conclusion=conclusion,
        tests=1,
        failures=0 if conclusion == "passed" else 1,
        skipped=0,
        retained_run_labels=tier.required_run_labels,
        lifecycle_receipt_retained=tier.lifecycle_receipt_required,
        junit_retained=True,
        diagnostic_files=(
            "command-transcript.txt",
            "console-output.txt",
        ),
    )


def test_campaign_owns_one_complete_canonical_tier_sequence() -> None:
    assert tuple(tier.name for tier in CANONICAL_ACCEPTANCE_TIERS) == (
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
        "fresh-1pga",
        "fresh-local-1pga",
        "fresh-2emo",
        "fresh-local-2emo",
        "fresh-canonical-3gb1",
        "fresh-local-canonical-3gb1",
        "fresh-5g53",
        "fresh-local-5g53",
    )
    assert all(
        tier.pytest_arguments
        and tier.timeout_seconds > 0
        and tier.zero_skip
        and tier.required_run_labels
        and tier.environment_configuration
        for tier in CANONICAL_ACCEPTANCE_TIERS
    )
    assert {
        tier.name: tier.source_bound.input_sha256
        for tier in CANONICAL_ACCEPTANCE_TIERS
        if tier.source_bound is not None
    } == {
        "fresh-1pga": (
            "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
        ),
        "fresh-local-1pga": (
            "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
        ),
        "fresh-2emo": (
            "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
        ),
        "fresh-local-2emo": (
            "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
        ),
        "fresh-canonical-3gb1": (
            "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
        ),
        "fresh-local-canonical-3gb1": (
            "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
        ),
        "fresh-5g53": (
            "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
        ),
        "fresh-local-5g53": (
            "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
        ),
    }


def test_source_bound_tiers_fix_current_exact_inputs_and_workflows() -> None:
    project_root = Path(__file__).resolve().parent.parent
    catalog = build_frozen_catalog(module_registrations())
    for tier in CANONICAL_ACCEPTANCE_TIERS:
        source_bound = tier.source_bound
        if source_bound is None:
            continue
        input_path = project_root / source_bound.input_path
        workflow_path = project_root / source_bound.workflow_path
        assert hashlib.sha256(input_path.read_bytes()).hexdigest() == (
            source_bound.input_sha256
        )
        workflow = decode_workflow_document(
            json.loads(workflow_path.read_text(encoding="utf-8"))
        )
        assert workflow.contract_lock
        assert all(
            catalog.require_contract(
                reference.contract_kind,
                reference.contract_id,
                reference.contract_version,
            ).contract_digest
            == reference.contract_digest
            for reference in workflow.contract_lock
        )


def test_campaign_definition_projects_every_execution_fact_from_that_sequence() -> None:
    definition = acceptance_definition()

    assert definition["schema_namespace"] == CAMPAIGN_DEFINITION_SCHEMA_NAMESPACE
    tiers = definition["tiers"]
    assert isinstance(tiers, list)
    assert [tier["name"] for tier in tiers] == [
        tier.name for tier in CANONICAL_ACCEPTANCE_TIERS
    ]
    assert tiers[0] == {
        "name": "installed-biohub-esmc",
        "pytest_arguments": [
            "tests/test_installed_backend_v2.py::test_installed_biohub_esmc_gate"
        ],
        "timeout_seconds": 30 * 60,
        "zero_skip": True,
        "junit_required": True,
        "required_run_labels": ["biohub-esmc"],
        "lifecycle_receipt_required": False,
        "environment_configuration": [
            ["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"]
        ],
        "source_bound": None,
    }
    assert tiers[-1]["source_bound"] == {
        "input_path": "examples/v2/structures/5G53.pdb",
        "input_sha256": (
            "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
        ),
        "workflow_path": "examples/v2/source-bound-5g53.workflow.json",
    }


def test_local_esm3_tier_requires_one_explicit_snapshot_root() -> None:
    tier = acceptance_tier("installed-local-esm3")

    assert tier.environment_configuration == (
        ("PROTEIN_WORKBENCH_ESM3_MODEL_ROOT",),
    )


def test_execution_profile_projects_only_one_tiers_declared_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setenv("PROTEIN_WORKBENCH_AMBIENT_UNKNOWN", "/ambient")
    monkeypatch.setenv("PYTHONPATH", "/ambient/source")
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid")

    environment = profile.environment_for(
        acceptance_tier("installed-proteinmpnn")
    )

    configured_names = {
        name
        for name in environment
        if name.startswith("PROTEIN_WORKBENCH_")
    }
    assert configured_names == {
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"
    }
    assert "PYTHONPATH" not in environment
    assert "HTTPS_PROXY" not in environment
    public_definition = profile.public_definition()
    assert public_definition["content_digest"].startswith("sha256:")
    assert len(public_definition["content_digest"]) == 71
    assert public_definition == {
        "content_digest": public_definition["content_digest"],
        "provider_configuration_names": sorted(
            profile.provider_configuration
        ),
        "remote_transport": {"proxy_policy": "direct"},
    }


@pytest.mark.parametrize(
    "replacement",
    (
        {"schema_namespace": "unknown-profile/v1"},
        {"remote_transport": {"proxy_policy": "guess"}},
        {"provider_configuration": {"UNDECLARED_PROVIDER_ROOT": "/tmp"}},
    ),
)
def test_execution_profile_rejects_values_outside_the_canonical_plan(
    tmp_path: Path,
    replacement: dict[str, object],
) -> None:
    profile_path = _write_profile(tmp_path)
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    document.update(replacement)
    profile_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeError):
        ExecutionProfile.load(profile_path)


def test_execution_profile_rejects_relative_configuration_paths(
    tmp_path: Path,
) -> None:
    profile_path = _write_profile(tmp_path)
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    first_name = next(iter(document["provider_configuration"]))
    document["provider_configuration"][first_name] = "relative/provider"
    profile_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeError, match="absolute paths"):
        ExecutionProfile.load(profile_path)


def test_execution_profile_preserves_credential_path_no_follow_semantics(
    tmp_path: Path,
) -> None:
    profile_path = _write_profile(tmp_path)
    token_path = tmp_path / "biohub-token"
    token_path.write_text("secret-token\n")
    token_path.chmod(0o600)
    link_path = tmp_path / "configured-token"
    link_path.symlink_to(token_path)
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    document["provider_configuration"][
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"
    ] = str(link_path)
    profile_path.write_text(json.dumps(document), encoding="utf-8")

    profile = ExecutionProfile.load(profile_path)

    assert profile.provider_configuration[
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"
    ] == str(link_path)


def test_prepare_binds_candidate_plan_revision_and_redacted_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))

    def build(command: list[str], **_kwargs: object) -> None:
        artifact_root = Path(command[-1])
        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / "protein_workbench.whl").write_bytes(b"wheel")
        (artifact_root / "protein_workbench.tar.gz").write_bytes(b"sdist")

    monkeypatch.setattr(campaign.subprocess, "run", build)

    manifest = prepare_campaign(root, profile)

    assert manifest == {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "source_revision": "a" * 40,
        "candidate": {
            "wheel": {
                "path": "artifacts/protein_workbench.whl",
                "sha256": (
                    "ba59926159d2aa256eb8739b8da7e2b574b960e1202c6d624cbe981cef996c91"
                ),
            },
            "sdist": {
                "path": "artifacts/protein_workbench.tar.gz",
                "sha256": (
                    "714772a9f82b2aeb4fa5f7092d00fe4ac4c9cdeb6800840b6ed39ea64c4d785a"
                ),
            },
        },
        "definition": acceptance_definition(),
        "execution_profile": profile.public_definition(),
        "state": "prepared",
        "executions": [],
    }
    persisted = json.loads((root / "campaign.json").read_text())
    assert persisted == manifest
    serialized = (root / "campaign.json").read_text()
    assert str(tmp_path / "configured") not in serialized


def test_campaign_admits_structured_outcomes_once_in_exact_serial_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))
    observed: list[tuple[str, set[str]]] = []

    def run_tier(
        campaign_root: Path,
        tier: object,
        environment: dict[str, str],
    ) -> TierExecutionOutcome:
        assert hasattr(tier, "name")
        tier_name = tier.name
        configured_names = {
            name
            for name in environment
            if name.startswith("PROTEIN_WORKBENCH_")
        }
        observed.append((tier_name, configured_names))
        return _outcome(campaign_root, tier_name, "passed")

    monkeypatch.setattr(campaign, "_run_tier", run_tier)

    completed = run_campaign(root, profile)

    assert [name for name, _configured in observed] == [
        tier.name for tier in CANONICAL_ACCEPTANCE_TIERS
    ]
    for tier, (_name, configured) in zip(
        CANONICAL_ACCEPTANCE_TIERS,
        observed,
        strict=True,
    ):
        expected = {
            name
            for alternatives in tier.environment_configuration
            for name in alternatives
            if name in profile.provider_configuration
        }
        assert configured == expected
    assert completed["state"] == "passed"
    executions = completed["executions"]
    assert isinstance(executions, list)
    assert [execution["tier"] for execution in executions] == [
        tier.name for tier in CANONICAL_ACCEPTANCE_TIERS
    ]
    assert all(
        execution["acceptance_result"] is not None
        for execution in executions
    )
    assert campaign_status(root) == {
        "state": "passed",
        "source_revision": "a" * 40,
        "passed_tiers": len(CANONICAL_ACCEPTANCE_TIERS),
        "total_tiers": len(CANONICAL_ACCEPTANCE_TIERS),
        "outcomes": {
            tier.name: "passed"
            for tier in CANONICAL_ACCEPTANCE_TIERS
        },
    }


def test_campaign_requires_the_candidate_bound_during_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    (root / "artifacts" / "protein_workbench.whl").unlink()
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))

    with pytest.raises(RuntimeError, match="candidate is missing"):
        run_campaign(root, profile)

    assert json.loads((root / "campaign.json").read_text())["state"] == (
        "prepared"
    )


def test_campaign_rejects_candidate_content_changed_after_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    (root / "artifacts" / "protein_workbench.whl").write_bytes(
        b"different-wheel"
    )
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))
    monkeypatch.setattr(
        campaign,
        "_run_tier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("changed candidate must not execute")
        ),
    )

    with pytest.raises(RuntimeError, match="candidate changed"):
        run_campaign(root, profile)


def test_campaign_rejects_private_profile_changed_after_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    prepared_profile = ExecutionProfile.load(_write_profile(tmp_path / "first"))
    replacement_profile = ExecutionProfile.load(_write_profile(tmp_path / "second"))
    root = tmp_path / "campaign"
    _prepared_campaign(root, prepared_profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))
    monkeypatch.setattr(
        campaign,
        "_run_tier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("changed profile must not execute")
        ),
    )

    with pytest.raises(RuntimeError, match="execution profile changed"):
        run_campaign(root, replacement_profile)


def test_campaign_stops_at_first_failed_outcome_without_making_it_a_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))
    observed: list[str] = []

    def run_tier(
        campaign_root: Path,
        tier: object,
        _environment: dict[str, str],
    ) -> TierExecutionOutcome:
        assert hasattr(tier, "name")
        observed.append(tier.name)
        conclusion = "failed" if len(observed) == 2 else "passed"
        return _outcome(campaign_root, tier.name, conclusion)

    monkeypatch.setattr(campaign, "_run_tier", run_tier)

    with pytest.raises(RuntimeError, match="acceptance tier failed"):
        run_campaign(root, profile)

    manifest = json.loads((root / "campaign.json").read_text())
    assert observed == [
        tier.name for tier in CANONICAL_ACCEPTANCE_TIERS[:2]
    ]
    assert manifest["state"] == "failed"
    assert manifest["executions"][0]["acceptance_result"] is not None
    assert manifest["executions"][1]["acceptance_result"] is None
    assert campaign_status(root)["passed_tiers"] == 1
    with pytest.raises(RuntimeError, match="campaign already started"):
        run_campaign(root, profile)


def test_passed_child_conclusion_cannot_authorize_incomplete_acceptance_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))

    def run_tier(
        campaign_root: Path,
        tier: object,
        _environment: dict[str, str],
    ) -> TierExecutionOutcome:
        assert hasattr(tier, "name")
        return replace(
            _outcome(campaign_root, tier.name, "passed"),
            retained_run_labels=(),
        )

    monkeypatch.setattr(campaign, "_run_tier", run_tier)

    with pytest.raises(RuntimeError, match="structurally incomplete"):
        run_campaign(root, profile)

    manifest = json.loads((root / "campaign.json").read_text())
    assert manifest["state"] == "failed"
    assert manifest["executions"] == []


def test_campaign_interruption_closes_only_finished_tier_executions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))
    attempts = 0

    def run_tier(
        campaign_root: Path,
        tier: object,
        _environment: dict[str, str],
    ) -> TierExecutionOutcome:
        nonlocal attempts
        assert hasattr(tier, "name")
        attempts += 1
        if attempts == 2:
            raise KeyboardInterrupt
        return _outcome(campaign_root, tier.name, "passed")

    monkeypatch.setattr(campaign, "_run_tier", run_tier)

    with pytest.raises(KeyboardInterrupt):
        run_campaign(root, profile)

    manifest = json.loads((root / "campaign.json").read_text())
    assert manifest["state"] == "interrupted"
    assert [execution["tier"] for execution in manifest["executions"]] == [
        CANONICAL_ACCEPTANCE_TIERS[0].name
    ]


def test_verifier_publishes_one_campaign_owned_structured_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier_name = "retained-evidence-probe"
    monkeypatch.setitem(
        verify_backend.TIERS,
        tier_name,
        verify_backend.Tier(
            ("tests/tier_probes/retained_evidence_probe.py",),
            zero_skip=True,
            retain_evidence_bundle=True,
        ),
    )
    results_root = tmp_path / "verification-results"
    outcome_path = tmp_path / "child-outcome.json"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT",
        str(results_root),
    )

    result = verify_backend.run(
        tier_name,
        (),
        acceptance_outcome_path=outcome_path,
    )

    assert result == 0
    outcome = TierExecutionOutcome.from_document(
        json.loads(outcome_path.read_bytes())
    )
    assert outcome.tier == tier_name
    assert outcome.conclusion == "passed"
    assert outcome.tests == 1
    assert outcome.failures == 0
    assert outcome.skipped == 0
    assert outcome.retained_run_labels == ("probe-run",)
    assert outcome.lifecycle_receipt_retained is False
    assert outcome.junit_retained is True
    assert outcome.diagnostic_files == (
        "command-transcript.txt",
        "console-output.txt",
        "environment-summary.json",
        "pytest.xml",
        "pytest-diagnostics.xml",
    )
    retained = results_root / outcome.retained_location
    assert json.loads(
        (retained / "evidence" / "tier-result.json").read_bytes()
    ) == outcome.to_document()


def test_verifier_admits_junit_once_before_projecting_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier_name = "retained-evidence-probe"
    monkeypatch.setitem(
        verify_backend.TIERS,
        tier_name,
        verify_backend.Tier(
            ("tests/tier_probes/retained_evidence_probe.py",),
            retain_evidence_bundle=True,
        ),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT",
        str(tmp_path / "verification-results"),
    )
    read_bytes = Path.read_bytes
    junit_reads = 0

    def counted_read_bytes(path: Path) -> bytes:
        nonlocal junit_reads
        if path.name == "pytest.xml":
            junit_reads += 1
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)

    assert verify_backend.run(tier_name, ()) == 0
    assert junit_reads == 1


def test_interpreter_digest_failure_remains_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = Path(sys.executable).resolve()
    path_open = Path.open

    def fail_for_interpreter(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> object:
        if path == executable:
            raise OSError("diagnostic unavailable")
        return path_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_for_interpreter)

    assert verify_backend._interpreter_digest() is None


def test_child_return_code_and_stdout_cannot_override_structured_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))

    def run_child(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        tier_name = command[-1]
        outcome_path = Path(command[command.index("--acceptance-outcome") + 1])
        write_tier_execution_outcome(
            outcome_path,
            _outcome(root, tier_name, "passed"),
        )
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "RETAINED VERIFICATION RESULT: /wrong/path\n"
                "BACKEND VERIFICATION RESULT: failed\n"
            ),
        )

    monkeypatch.setattr(campaign.subprocess, "run", run_child)

    completed = run_campaign(root, profile)

    assert completed["state"] == "passed"
    assert all(
        execution["conclusion"] == "passed"
        for execution in completed["executions"]
    )


def test_completed_child_without_structured_outcome_fails_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))
    monkeypatch.setattr(
        campaign.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="diagnostic only\n",
        ),
    )

    with pytest.raises(RuntimeError, match="structured outcome"):
        run_campaign(root, profile)

    manifest = json.loads((root / "campaign.json").read_text())
    assert manifest["state"] == "failed"
    assert manifest["executions"] == []


def test_structured_outcome_rejects_noncanonical_retained_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import verification.acceptance_campaign as campaign

    profile = ExecutionProfile.load(_write_profile(tmp_path))
    root = tmp_path / "campaign"
    _prepared_campaign(root, profile)
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("a" * 40, False))

    def run_tier(
        campaign_root: Path,
        tier: object,
        _environment: dict[str, str],
    ) -> TierExecutionOutcome:
        assert hasattr(tier, "name")
        outcome = _outcome(campaign_root, tier.name, "passed")
        escaped_root = campaign_root / "results"
        for run_label in outcome.retained_run_labels:
            (escaped_root / "evidence" / "runs" / run_label).mkdir(
                parents=True,
                exist_ok=True,
            )
        (escaped_root / "pytest.xml").write_text("<testsuite/>\n")
        for diagnostic in outcome.diagnostic_files:
            (escaped_root / diagnostic).write_text("diagnostic\n")
        return replace(
            outcome,
            retained_location=(Path(tier.name) / "..").as_posix(),
        )

    monkeypatch.setattr(campaign, "_run_tier", run_tier)

    with pytest.raises(RuntimeError, match="retained location is invalid"):
        run_campaign(root, profile)

    assert json.loads((root / "campaign.json").read_text())["state"] == (
        "failed"
    )
