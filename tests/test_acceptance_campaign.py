"""Contract tests for qualification and serial frozen certification."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from core import build_discovered_frozen_catalog, parse_workflow_document
from protein_workbench_public import bundle_digest

from scripts.acceptance_campaign import (
    ACCEPTANCE_TIER_ORDER,
    CAMPAIGN_SCHEMA_NAMESPACE,
    INPUT_DIGESTS,
    PROFILE_SCHEMA_NAMESPACE,
    PROVIDER_CONFIGURATION_CONTRACTS,
    SOURCE_BOUND_CONTRACTS,
    ExecutionProfile,
    acceptance_definition,
    campaign_status,
    certify_through,
    prepare_campaign,
    qualify_all,
    qualify_tier,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_profile(tmp_path: Path, *, proxy_policy: str = "direct") -> Path:
    configured = tmp_path / "configured"
    configured.mkdir()
    variables = {
        variable
        for names in PROVIDER_CONFIGURATION_CONTRACTS.values()
        for variable in names
    }
    variables.remove("HF_HOME")
    profile_path = tmp_path / "acceptance-profile.json"
    profile_path.write_text(
        json.dumps({
            "schema_namespace": PROFILE_SCHEMA_NAMESPACE,
            "provider_configuration": {
                variable: str(configured)
                for variable in sorted(variables)
            },
            "remote_transport": {"proxy_policy": proxy_policy},
        }),
        encoding="utf-8",
    )
    return profile_path


def _write_campaign(root: Path, *, qualification: list[dict] | None = None) -> dict:
    import scripts.acceptance_campaign as campaign

    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True)
    (artifact_root / "protein_workbench.whl").write_bytes(b"wheel")
    (artifact_root / "protein_workbench.tar.gz").write_bytes(b"sdist")
    manifest = {
        **acceptance_definition(),
        "source_revision": "a" * 40,
        "source_dirty": False,
        "installed_artifacts": campaign._artifact_records(artifact_root),
        "provider_configuration_identities": {"frozen": "configuration"},
        "provider_asset_identities": {"frozen": "assets"},
        "execution_profile_identity": "sha256:" + "1" * 64,
        "qualification": {"attempts": qualification or []},
        "certification": {"state": "not_started", "results": []},
    }
    (root / "campaign.json").write_bytes(campaign._canonical_bytes(manifest))
    return manifest


def _passing_qualification() -> list[dict]:
    return [
        {
            "tier": tier,
            "attempt": 0,
            "outcome": "passed",
            "evidence_bundle_digest": "sha256:" + "2" * 64,
            "verification_result": f"qualification-results/{tier}/passed",
        }
        for tier in ACCEPTANCE_TIER_ORDER
    ]


def _result(root: Path, phase: str, tier: str, outcome: str) -> SimpleNamespace:
    result_dir = root / f"{phase}-results" / tier / outcome
    result_dir.mkdir(parents=True)
    (result_dir / "evidence.json").write_text(tier, encoding="utf-8")
    return SimpleNamespace(
        returncode=0 if outcome == "passed" else 1,
        output=f"RETAINED VERIFICATION RESULT: {result_dir}\n",
    )


def test_source_bound_acceptance_contracts_are_current_and_source_exact() -> None:
    catalog = build_discovered_frozen_catalog()
    for tier_name, contract in SOURCE_BOUND_CONTRACTS.items():
        input_path = PROJECT_ROOT / contract.input_path
        workflow_path = PROJECT_ROOT / contract.workflow_path
        assert hashlib.sha256(input_path.read_bytes()).hexdigest() == (
            INPUT_DIGESTS[tier_name]
        )
        workflow = parse_workflow_document(
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


def test_acceptance_definition_binds_one_complete_certification_order() -> None:
    definition = acceptance_definition()

    assert definition["schema_namespace"] == CAMPAIGN_SCHEMA_NAMESPACE
    assert definition["tier_order"] == list(ACCEPTANCE_TIER_ORDER)
    assert definition["protocol_digest"] == bundle_digest()
    assert definition["catalog_contract_digest"] == (
        build_discovered_frozen_catalog().contract_digest
    )
    assert definition["execution"] == {
        "child_processes": "one_at_a_time",
        "pytest_xdist": False,
        "concurrent_tiers": False,
        "nested_local_model_processes": False,
        "resident_model_instances_per_local_model": 1,
    }
    assert definition["source_bound_inputs"] == INPUT_DIGESTS
    assert list(definition["tier_contracts"]) == list(ACCEPTANCE_TIER_ORDER)


def test_execution_profile_is_explicit_private_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setenv("HTTPS_PROXY", "http://secret-proxy.invalid")
    monkeypatch.setenv("PYTHONPATH", "/ambient/source")
    monkeypatch.setenv("PROTEIN_WORKBENCH_AMBIENT_UNKNOWN", "/ambient/value")

    environment = profile.environment()

    assert environment["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"] == str(
        (tmp_path / "configured").resolve()
    )
    assert "HTTPS_PROXY" not in environment
    assert "PYTHONPATH" not in environment
    assert "PROTEIN_WORKBENCH_AMBIENT_UNKNOWN" not in environment
    assert str(tmp_path) not in profile.path_free_identity(
        {"frozen": "configuration"}
    )


def test_profile_context_preserves_the_exact_inherited_transport_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    profile = ExecutionProfile.load(
        _write_profile(tmp_path, proxy_policy="inherit")
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:1082")
    monkeypatch.setenv("CAMPAIGN_PARENT_SENTINEL", "preserved")
    expected = profile.path_free_identity({"frozen": "configuration"})

    with campaign._configured_environment(profile):
        assert os.environ["HTTPS_PROXY"] == "http://proxy.invalid:1082"
        assert os.environ["CAMPAIGN_PARENT_SENTINEL"] == "preserved"
        assert profile.path_free_identity({"frozen": "configuration"}) == (
            expected
        )


def test_documented_cli_prepares_one_campaign_without_repository_import(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign"
    profile_path = _write_profile(tmp_path)
    result_path = tmp_path / "result.json"
    launcher = textwrap.dedent(
        """
        import importlib.util
        import json
        from pathlib import Path
        import sys

        project_root = Path(sys.argv[1]).resolve()
        script_path = project_root / "scripts" / "acceptance_campaign.py"
        sys.path = [
            entry
            for entry in sys.path
            if Path(entry or ".").resolve() != project_root
        ]
        spec = importlib.util.spec_from_file_location(
            "acceptance_campaign_documented_script",
            script_path,
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module._git_authority = lambda: ("d" * 40, False)
        module._configuration_identities = lambda: {"frozen": "configuration"}
        module._provider_asset_identities = lambda: {"frozen": "assets"}
        campaign_root = Path(sys.argv[2])
        profile_path = Path(sys.argv[3])
        result_path = Path(sys.argv[4])
        sys.argv = [
            str(script_path),
            "prepare",
            str(campaign_root),
            "--profile",
            str(profile_path),
        ]
        assert module.main() == 0
        manifest = json.loads((campaign_root / "campaign.json").read_text())
        result_path.write_text(json.dumps({
            "tier_order": manifest["tier_order"],
            "artifact_kinds": [
                artifact["kind"]
                for artifact in manifest["installed_artifacts"]
            ],
            "qualification": manifest["qualification"],
            "certification": manifest["certification"],
            "repo_root_on_sys_path": any(
                Path(entry or ".").resolve() == project_root
                for entry in sys.path
            ),
        }))
        """
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            launcher,
            str(PROJECT_ROOT),
            str(campaign_root),
            str(profile_path),
            str(result_path),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "artifact_kinds": ["wheel", "sdist"],
        "qualification": {"attempts": []},
        "certification": {"state": "not_started", "results": []},
        "repo_root_on_sys_path": False,
    }


def test_prepare_failure_never_publishes_a_partial_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_git_authority", lambda: ("e" * 40, False))
    monkeypatch.setattr(
        campaign,
        "_configuration_identities",
        lambda: {"frozen": "configuration"},
    )
    monkeypatch.setattr(
        campaign,
        "_provider_asset_identities",
        lambda: {"frozen": "assets"},
    )
    monkeypatch.setattr(
        campaign.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "build_backend")
        ),
    )

    with pytest.raises(subprocess.CalledProcessError):
        prepare_campaign(root, profile)

    assert not root.exists()


def test_qualification_failure_is_non_authoritative_and_rerunnable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    _write_campaign(root)
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)
    outcomes = iter(("failed", "passed"))
    monkeypatch.setattr(
        campaign,
        "_run_tier",
        lambda _root, phase, tier, _environment: _result(
            root, phase, tier, next(outcomes)
        ),
    )
    tier = ACCEPTANCE_TIER_ORDER[6]

    with pytest.raises(RuntimeError, match="qualification tier failed"):
        qualify_tier(root, tier, profile)
    completed = qualify_tier(root, tier, profile)

    attempts = completed["qualification"]["attempts"]
    assert [(item["attempt"], item["outcome"]) for item in attempts] == [
        (0, "failed"),
        (1, "passed"),
    ]
    assert completed["certification"]["state"] == "not_started"
    assert all(item["authoritative"] is False for item in attempts)


def test_qualification_all_prioritizes_risk_and_skips_current_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    already_passed = _passing_qualification()[:1]
    _write_campaign(root, qualification=already_passed)
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)
    observed: list[str] = []

    def run(_root, phase, tier, _environment):
        observed.append(tier)
        return _result(root, phase, tier, "passed")

    monkeypatch.setattr(campaign, "_run_tier", run)
    prioritized = ACCEPTANCE_TIER_ORDER[7:9]

    completed = qualify_all(root, profile, prioritize=prioritized)

    expected = [
        *prioritized,
        *(
            tier
            for tier in ACCEPTANCE_TIER_ORDER
            if tier not in {*prioritized, ACCEPTANCE_TIER_ORDER[0]}
        ),
    ]
    assert observed == expected
    assert campaign_status(root, profile)["state"] == "qualified"
    assert len(completed["qualification"]["attempts"]) == len(
        ACCEPTANCE_TIER_ORDER
    )


def test_certification_requires_all_latest_qualification_results_to_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    qualification = _passing_qualification()[:-1]
    _write_campaign(root, qualification=qualification)
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)

    with pytest.raises(RuntimeError, match="qualification is incomplete"):
        certify_through(root, ACCEPTANCE_TIER_ORDER[0], profile)


def test_certification_is_fresh_canonical_serial_and_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    _write_campaign(root, qualification=_passing_qualification())
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)
    observed: list[str] = []

    def run(_root, phase, tier, _environment):
        assert phase == "certification"
        observed.append(tier)
        return _result(root, phase, tier, "passed")

    monkeypatch.setattr(campaign, "_run_tier", run)
    completed = certify_through(root, ACCEPTANCE_TIER_ORDER[1], profile)

    assert observed == list(ACCEPTANCE_TIER_ORDER[:2])
    results = completed["certification"]["results"]
    assert [item["tier"] for item in results] == observed
    assert all(item["outcome"] == "passed" for item in results)
    assert all(item["authoritative"] is True for item in results)
    assert completed["certification"]["state"] == "paused"
    assert campaign_status(root, profile)["state"] == "certification_paused"


def test_failed_certification_is_terminal_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    _write_campaign(root, qualification=_passing_qualification())
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)
    calls = 0

    def fail(_root, phase, tier, _environment):
        nonlocal calls
        calls += 1
        return _result(root, phase, tier, "failed")

    monkeypatch.setattr(campaign, "_run_tier", fail)
    first = ACCEPTANCE_TIER_ORDER[0]

    with pytest.raises(RuntimeError, match="certification tier failed"):
        certify_through(root, first, profile)
    with pytest.raises(RuntimeError, match="certification is terminated"):
        certify_through(root, first, profile)

    retained = json.loads((root / "campaign.json").read_bytes())
    assert retained["certification"]["state"] == "failed"
    assert retained["certification"]["results"][0]["outcome"] == "failed"
    assert calls == 1


def test_final_certification_result_atomically_closes_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    manifest = _write_campaign(root, qualification=_passing_qualification())
    manifest["certification"] = {
        "state": "running",
        "results": [
            {
                "tier": tier,
                "ordinal": ordinal,
                "outcome": "passed",
                "authoritative": True,
            }
            for ordinal, tier in enumerate(ACCEPTANCE_TIER_ORDER[:-1])
        ],
    }
    (root / "campaign.json").write_bytes(campaign._canonical_bytes(manifest))
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)
    monkeypatch.setattr(
        campaign,
        "_run_tier",
        lambda _root, phase, tier, _environment: _result(
            root, phase, tier, "passed"
        ),
    )

    certify_through(root, ACCEPTANCE_TIER_ORDER[-1], profile)

    retained = json.loads((root / "campaign.json").read_bytes())
    assert retained["certification"]["state"] == "passed"
    assert campaign_status(root, profile)["state"] == "certification_passed"


def test_interruption_is_durable_and_qualification_can_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    _write_campaign(root)
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)
    retained_result = _result(
        root,
        "qualification",
        ACCEPTANCE_TIER_ORDER[0],
        "failed",
    )
    monkeypatch.setattr(
        campaign,
        "_run_tier",
        lambda *_args: (_ for _ in ()).throw(
            campaign.TierExecutionInterrupted(retained_result.output)
        ),
    )

    with pytest.raises(campaign.TierExecutionInterrupted):
        qualify_tier(root, ACCEPTANCE_TIER_ORDER[0], profile)

    retained = json.loads((root / "campaign.json").read_bytes())
    assert retained["qualification"]["attempts"][0]["outcome"] == (
        "interrupted"
    )
    assert retained["qualification"]["attempts"][0][
        "verification_result"
    ].endswith("/failed")
    assert campaign_status(root, profile)["state"] == "qualifying"


def test_orphaned_started_certification_is_recovered_as_terminal_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "campaign"
    manifest = _write_campaign(root, qualification=_passing_qualification())
    manifest["certification"] = {
        "state": "running",
        "results": [{
            "tier": ACCEPTANCE_TIER_ORDER[0],
            "ordinal": 0,
            "outcome": "started",
            "authoritative": True,
        }],
    }
    import scripts.acceptance_campaign as campaign

    (root / "campaign.json").write_bytes(campaign._canonical_bytes(manifest))
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)

    assert campaign_status(root, profile)["state"] == (
        "certification_interrupted"
    )
    retained = json.loads((root / "campaign.json").read_bytes())
    assert retained["certification"]["state"] == "interrupted"
    assert retained["certification"]["results"][0]["outcome"] == (
        "interrupted"
    )


def test_controller_exit_before_first_certification_tier_recovers_as_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "campaign"
    manifest = _write_campaign(root, qualification=_passing_qualification())
    manifest["certification"]["state"] = "running"
    import scripts.acceptance_campaign as campaign

    (root / "campaign.json").write_bytes(campaign._canonical_bytes(manifest))
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setattr(campaign, "_assert_candidate", lambda *_args: None)

    assert campaign_status(root, profile)["state"] == "certification_paused"
    retained = json.loads((root / "campaign.json").read_bytes())
    assert retained["certification"] == {"state": "paused", "results": []}
