"""Public contracts for one simple serial acceptance campaign."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import build_discovered_frozen_catalog, parse_workflow_document
from modules.acceptance_verification import ACCEPTANCE_TIER_CONTRACTS
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
    prepare_campaign,
    run_campaign,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_profile(tmp_path: Path) -> Path:
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
            "remote_transport": {"proxy_policy": "direct"},
        }),
        encoding="utf-8",
    )
    return profile_path


@pytest.mark.parametrize(
    "replacement",
    (
        {"schema_namespace": "unknown-profile/v1"},
        {"remote_transport": {"proxy_policy": "guess"}},
        {"provider_configuration": {"UNDECLARED_PROVIDER_ROOT": "/tmp"}},
    ),
)
def test_execution_profile_rejects_values_outside_its_contract(
    tmp_path: Path,
    replacement: dict[str, object],
) -> None:
    profile_path = _write_profile(tmp_path)
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    document.update(replacement)
    profile_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeError):
        ExecutionProfile.load(profile_path)


def _prepared_campaign(root: Path) -> dict[str, object]:
    (root / "artifacts").mkdir(parents=True)
    manifest: dict[str, object] = {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "source_revision": "a" * 40,
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "state": "prepared",
        "results": [],
    }
    (root / "campaign.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return manifest


def _execution(root: Path, tier: str, outcome: str) -> SimpleNamespace:
    result_dir = root / "results" / tier / outcome
    result_dir.mkdir(parents=True)
    (result_dir / "tier-result.json").write_text(
        json.dumps({"tier": tier, "passed": outcome == "passed"}),
        encoding="utf-8",
    )
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


def test_acceptance_definition_is_one_serial_scientific_run() -> None:
    definition = acceptance_definition()

    assert definition == {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "tier_contracts": {
            name: {
                "pytest_arguments": list(contract.pytest_arguments),
                "timeout_seconds": contract.timeout_seconds,
                "required_run_labels": list(contract.required_run_labels),
                "lifecycle_receipt_required": (
                    contract.lifecycle_receipt_required
                ),
            }
            for name, contract in ACCEPTANCE_TIER_CONTRACTS.items()
        },
    }


def test_execution_profile_replaces_ambient_project_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    monkeypatch.setenv("PROTEIN_WORKBENCH_AMBIENT_UNKNOWN", "/ambient")
    monkeypatch.setenv("PYTHONPATH", "/ambient/source")
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid")

    environment = profile.environment()

    assert "PROTEIN_WORKBENCH_AMBIENT_UNKNOWN" not in environment
    assert "PYTHONPATH" not in environment
    assert "HTTPS_PROXY" not in environment
    assert environment["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"] == str(
        tmp_path / "configured"
    )


def test_prepare_builds_one_clean_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

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
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "state": "prepared",
        "results": [],
    }
    assert json.loads((root / "campaign.json").read_text()) == manifest


def test_campaign_runs_each_real_tier_once_in_canonical_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    _prepared_campaign(root)
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    observed: list[str] = []

    def run_tier(
        campaign_root: Path,
        tier_name: str,
        _environment: object,
    ) -> SimpleNamespace:
        observed.append(tier_name)
        return _execution(campaign_root, tier_name, "passed")

    monkeypatch.setattr(campaign, "_run_tier", run_tier)

    completed = run_campaign(root, profile)

    assert observed == list(ACCEPTANCE_TIER_ORDER)
    assert completed["state"] == "passed"
    assert [result["tier"] for result in completed["results"]] == list(
        ACCEPTANCE_TIER_ORDER
    )
    assert all(
        result["outcome"] == "passed" for result in completed["results"]
    )
    assert all(
        result["verification_result"].startswith("results/")
        for result in completed["results"]
    )
    assert campaign_status(root) == {
        "state": "passed",
        "source_revision": "a" * 40,
        "passed_tiers": len(ACCEPTANCE_TIER_ORDER),
        "total_tiers": len(ACCEPTANCE_TIER_ORDER),
        "outcomes": {
            tier: "passed" for tier in ACCEPTANCE_TIER_ORDER
        },
    }


def test_campaign_stops_at_the_first_scientific_failure_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.acceptance_campaign as campaign

    root = tmp_path / "campaign"
    _prepared_campaign(root)
    profile = ExecutionProfile.load(_write_profile(tmp_path))
    observed: list[str] = []

    def run_tier(
        campaign_root: Path,
        tier_name: str,
        _environment: object,
    ) -> SimpleNamespace:
        observed.append(tier_name)
        outcome = "failed" if len(observed) == 2 else "passed"
        return _execution(campaign_root, tier_name, outcome)

    monkeypatch.setattr(campaign, "_run_tier", run_tier)

    with pytest.raises(RuntimeError, match="acceptance tier failed"):
        run_campaign(root, profile)

    manifest = json.loads((root / "campaign.json").read_text())
    assert observed == list(ACCEPTANCE_TIER_ORDER[:2])
    assert manifest["state"] == "failed"
    assert [result["outcome"] for result in manifest["results"]] == [
        "passed",
        "failed",
    ]
    with pytest.raises(RuntimeError, match="campaign already started"):
        run_campaign(root, profile)
