"""Fast contracts for retained installed public Run evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any

import pytest

from modules.acceptance_verification import ACCEPTANCE_TIER_CONTRACTS
from protein_workbench_public import ProtocolValidationError
from scripts.acceptance_campaign import acceptance_definition
from tests.acceptance.retained_evidence import (
    retain_proteinmpnn_lifecycle,
    require_retained_evidence,
    retain_rest_run,
    retain_service_run,
)


TIER = "installed-fixture"
RUN_LABEL = "fixture-run"
VALUE = b'{"value":{"score":0.75}}\n'
ARTIFACT = b"fixture artifact\n"


EXPECTED_INSTALLED_RUNS = {
    "installed-biohub-esmc": ("biohub-esmc",),
    "installed-biohub-esm3": (
        "biohub-medium-generate-sequence",
        "biohub-medium-generate-structure",
        "biohub-medium-generate-paired",
        "biohub-open-generate-sequence",
        "biohub-open-generate-structure",
        "biohub-open-generate-paired",
    ),
    "installed-biohub-esmfold2": ("biohub-esmfold2",),
    "installed-local-esm3": (
        "local-esm3-generate-paired",
        "local-esm3-generate-sequence",
        "local-esm3-generate-structure",
    ),
    "installed-local-esmfold2": ("local-esmfold2",),
    "installed-mkdssp": ("mkdssp",),
    "installed-proteinmpnn": (
        "proteinmpnn-design",
        "proteinmpnn-score",
        "proteinmpnn-native-score",
        "proteinmpnn-sibling-design",
    ),
    "installed-simplefold-folding": ("simplefold-folding",),
    "installed-simplefold-confidence": ("simplefold-confidence",),
    "installed-soluprot": ("soluprot-full", "soluprot-no-tm"),
    "installed-protein-sol": ("protein-sol",),
}
EXPECTED_FRESH_RUNS = {
    "fresh-1pga": ("fresh-1pga",),
    "fresh-2emo": ("fresh-2emo",),
    "fresh-canonical-3gb1": ("fresh-canonical-3gb1",),
    "fresh-5g53": ("fresh-5g53",),
}


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _typed_value_metadata() -> dict[str, Any]:
    output = _projection()["outputs"][0]
    return {
        "typed_value": {
            "node_id": output["node_id"],
            "output_port": output["output_port"],
            "port_type": output["port_type"],
            "port_content_digest": output["content_digest"],
            "value_manifest_reference": output[
                "value_manifest_reference"
            ],
            "value_index": 0,
            "value_count": output["value_count"],
            "value_content_digest": _digest(VALUE),
            "size": len(VALUE),
        }
    }


def test_tier_contracts_declare_only_run_labels_and_lifecycle_need() -> None:
    assert {
        name: contract.required_run_labels
        for name, contract in ACCEPTANCE_TIER_CONTRACTS.items()
    } == {**EXPECTED_INSTALLED_RUNS, **EXPECTED_FRESH_RUNS}
    assert {
        name
        for name, contract in ACCEPTANCE_TIER_CONTRACTS.items()
        if contract.lifecycle_receipt_required
    } == {"installed-proteinmpnn", "fresh-2emo"}


def test_campaign_freezes_the_minimal_tier_evidence_contract() -> None:
    contracts = acceptance_definition()["tier_contracts"]

    assert contracts["installed-proteinmpnn"]["required_run_labels"] == list(
        EXPECTED_INSTALLED_RUNS["installed-proteinmpnn"]
    )
    assert contracts["installed-proteinmpnn"][
        "lifecycle_receipt_required"
    ] is True
    assert contracts["installed-biohub-esmc"][
        "lifecycle_receipt_required"
    ] is False


def _projection() -> dict[str, Any]:
    result_identity = "sha256:" + "4" * 64
    return {
        "project_id": "project-fixture",
        "run_id": "run-fixture",
        "workflow_commit_id": "workflow-commit-" + "5" * 64,
        "workflow_commit_revision": 1,
        "workflow_digest": "sha256:" + "6" * 64,
        "status": "succeeded",
        "ledger_cursor": "cursor-1",
        "terminal_sequence": 1,
        "node_dispositions": [
            {
                "node_id": "score",
                "outcome": "succeeded",
                "resolution": "executed",
                "terminal_sequence": 1,
                "blocked_by": [],
            }
        ],
        "outputs": [
            {
                "node_id": "score",
                "output_port": "scores",
                "port_type": {
                    "contract_kind": "port_type",
                    "contract_id": "fixture.score",
                    "contract_version": "1.0.0",
                    "contract_digest": "sha256:" + "1" * 64,
                },
                "content_digest": "sha256:" + "2" * 64,
                "result_identity": result_identity,
                "materialization": {
                    "run_id": "run-fixture",
                    "resolution": "executed",
                },
                "producer_provenance": {
                    "producer_run_id": "run-fixture",
                    "producer_result_identity": result_identity,
                    "output_port": "scores",
                },
                "value_manifest_reference": "sha256:" + "3" * 64,
                "value_count": 1,
            }
        ],
        "artifact_index": [
            {
                "artifact_reference": "artifact-fixture",
                "artifact_kind": "standalone",
                "node_id": "score",
                "output_port": "scores",
                "filename": "scores.txt",
                "media_type": "text/plain",
                "content_digest": _digest(ARTIFACT),
                "size": len(ARTIFACT),
            }
        ],
    }


def _events() -> tuple[dict[str, Any], ...]:
    return ({
        "schema_namespace": "protein-workbench-public/v2",
        "project_id": "project-fixture",
        "run_id": "run-fixture",
        "sequence": 1,
        "cursor": "cursor-1",
        "emitted_at": "2026-08-17T00:00:00+00:00",
        "event": {"type": "run_terminal", "status": "succeeded"},
    },)


def _write_complete(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING", str(root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_VERIFICATION_TIER", TIER)
    retain_service_run(
        RUN_LABEL,
        catalog=SimpleNamespace(
            catalog_descriptor_bytes=b'{"catalog":"fixture"}\n'
        ),
        service=_Service(),
        projection=_projection(),
        events=_events(),
    )


class _Service:
    def typed_value(
        self,
        project_id: str,
        run_id: str,
        node_id: str,
        output_port: str,
        value_index: int,
    ) -> tuple[dict[str, Any], bytes]:
        assert (
            project_id,
            run_id,
            node_id,
            output_port,
            value_index,
        ) == ("project-fixture", "run-fixture", "score", "scores", 0)
        output = _projection()["outputs"][0]
        return (
            {
                "typed_value": {
                    "node_id": node_id,
                    "output_port": output_port,
                    "port_type": output["port_type"],
                    "port_content_digest": output["content_digest"],
                    "value_manifest_reference": output[
                        "value_manifest_reference"
                    ],
                    "value_index": value_index,
                    "value_count": 1,
                    "value_content_digest": _digest(VALUE),
                    "size": len(VALUE),
                }
            },
            VALUE,
        )

    def artifact(
        self,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        assert (project_id, run_id, artifact_reference) == (
            "project-fixture",
            "run-fixture",
            "artifact-fixture",
        )
        return _projection()["artifact_index"][0], ARTIFACT


class _RestClient:
    def typed_value(
        self,
        request: dict[str, Any],
        output: dict[str, Any],
    ) -> tuple[dict[str, Any], bytes]:
        assert request == {
            "project_id": "project-fixture",
            "run_id": "run-fixture",
            "node_id": "score",
            "output_port": "scores",
            "value_index": 0,
        }
        assert output == _projection()["outputs"][0]
        return _typed_value_metadata(), VALUE

    def artifact(
        self,
        request: dict[str, Any],
        metadata: dict[str, Any],
    ) -> bytes:
        assert request == {
            "project_id": "project-fixture",
            "run_id": "run-fixture",
            "artifact_reference": "artifact-fixture",
        }
        assert metadata == _projection()["artifact_index"][0]
        return ARTIFACT


def test_service_run_writes_complete_minimal_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING", str(tmp_path))
    monkeypatch.setenv("PROTEIN_WORKBENCH_VERIFICATION_TIER", TIER)
    projection = _projection()

    retain_service_run(
        RUN_LABEL,
        catalog=SimpleNamespace(
            catalog_descriptor_bytes=b'{"catalog":"fixture"}\n'
        ),
        service=_Service(),
        projection=projection,
        events=_events(),
    )

    require_retained_evidence(
        tmp_path,
        required_runs=(RUN_LABEL,),
    )
    run_root = tmp_path / "runs" / RUN_LABEL
    assert json.loads((run_root / "projection.json").read_bytes()) == projection
    assert (run_root / "values" / "000000.bin").read_bytes() == VALUE
    assert (run_root / "artifacts" / "000000.bin").read_bytes() == ARTIFACT


def test_service_run_rejects_an_invalid_public_projection_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING", str(tmp_path))
    monkeypatch.setenv("PROTEIN_WORKBENCH_VERIFICATION_TIER", TIER)
    invalid_projection = {**_projection(), "legacy_status": "finished"}

    with pytest.raises(ProtocolValidationError):
        retain_service_run(
            RUN_LABEL,
            catalog=SimpleNamespace(
                catalog_descriptor_bytes=b'{"catalog":"fixture"}\n'
            ),
            service=_Service(),
            projection=invalid_projection,
            events=_events(),
        )

    assert list(tmp_path.iterdir()) == []


def test_service_run_rejects_an_invalid_public_event_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING", str(tmp_path))
    monkeypatch.setenv("PROTEIN_WORKBENCH_VERIFICATION_TIER", TIER)
    invalid_event = {**_events()[0], "legacy_status": "finished"}

    with pytest.raises(ProtocolValidationError):
        retain_service_run(
            RUN_LABEL,
            catalog=SimpleNamespace(
                catalog_descriptor_bytes=b'{"catalog":"fixture"}\n'
            ),
            service=_Service(),
            projection=_projection(),
            events=(invalid_event,),
        )

    assert list(tmp_path.iterdir()) == []


def test_rest_run_uses_the_same_minimal_bundle_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING", str(tmp_path))
    monkeypatch.setenv("PROTEIN_WORKBENCH_VERIFICATION_TIER", TIER)

    retain_rest_run(
        RUN_LABEL,
        catalog=SimpleNamespace(
            catalog_descriptor_bytes=b'{"catalog":"fixture"}\n'
        ),
        client=_RestClient(),
        projection=_projection(),
        events=_events(),
    )

    require_retained_evidence(
        tmp_path,
        required_runs=(RUN_LABEL,),
    )
    retained = json.loads(
        (tmp_path / "runs" / RUN_LABEL / "typed-values.json").read_bytes()
    )
    assert retained == [{
        "descriptor": _typed_value_metadata()["typed_value"],
        "payload": "values/000000.bin",
    }]


def test_generic_pytest_only_bundle_is_not_installed_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "tier-result.json").write_text('{"passed":true}\n')

    with pytest.raises(AssertionError):
        require_retained_evidence(
            tmp_path,
            required_runs=(RUN_LABEL,),
        )


@pytest.mark.parametrize(
    "missing",
    ("run", "typed-value", "artifact"),
)
def test_missing_public_run_evidence_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    _write_complete(tmp_path, monkeypatch)
    run_root = tmp_path / "runs" / RUN_LABEL
    if missing == "run":
        shutil.rmtree(run_root)
    elif missing == "typed-value":
        (run_root / "values" / "000000.bin").unlink()
    else:
        (run_root / "artifacts" / "000000.bin").unlink()

    with pytest.raises(AssertionError):
        require_retained_evidence(
            tmp_path,
            required_runs=(RUN_LABEL,),
        )


def test_required_lifecycle_receipt_cannot_be_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_complete(tmp_path, monkeypatch)

    with pytest.raises(AssertionError):
        require_retained_evidence(
            tmp_path,
            required_runs=(RUN_LABEL,),
            lifecycle_required=True,
        )


def test_proteinmpnn_lifecycle_receipt_contains_only_direct_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_complete(tmp_path, monkeypatch)

    retain_proteinmpnn_lifecycle(load_count=1)

    require_retained_evidence(
        tmp_path,
        required_runs=(RUN_LABEL,),
        lifecycle_required=True,
    )
    assert json.loads((tmp_path / "model-lifecycle.json").read_bytes()) == {
        "model": "proteinmpnn",
        "load_count": 1,
    }


def test_fresh_2emo_lifecycle_receipt_records_release_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_complete(tmp_path, monkeypatch)

    retain_proteinmpnn_lifecycle(
        load_count=1,
        release="before-protein-sol",
    )

    require_retained_evidence(
        tmp_path,
        required_runs=(RUN_LABEL,),
        lifecycle_required=True,
    )
    assert json.loads((tmp_path / "model-lifecycle.json").read_bytes()) == {
        "model": "proteinmpnn",
        "load_count": 1,
        "release": "before-protein-sol",
    }


def test_legacy_root_level_evidence_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_complete(tmp_path, monkeypatch)
    (tmp_path / "workflow.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        require_retained_evidence(
            tmp_path,
            required_runs=(RUN_LABEL,),
        )
