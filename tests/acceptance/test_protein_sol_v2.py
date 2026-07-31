"""Exact local Protein-Sol inference through the public V2 Run seam."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from modules.solubility.adapter import (
    configured_protein_sol_runtime_fingerprint,
    protein_sol_readiness,
)
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events


pytestmark = [pytest.mark.acceptance, pytest.mark.local_provider]

EXTERNAL_ROOT = Path("/Users/sorachan/Documents/ESM-workflow-NEXT")
SOURCE_ROOT = EXTERNAL_ROOT / "vendor/protein-sol"
FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "modules/solubility/fixtures"
)

def _fixture_sequences() -> tuple[str, ...]:
    sequences: list[str] = []
    current: list[str] = []
    for line in (
        FIXTURE_ROOT / "protein_sol_input.fasta"
    ).read_text().splitlines():
        if line.startswith(">"):
            if current:
                sequences.append("".join(current))
                current = []
            continue
        current.append(line.strip())
    if current:
        sequences.append("".join(current))
    return tuple(sequences)


SEQUENCES = _fixture_sequences()
with (FIXTURE_ROOT / "protein_sol_expected.csv").open(newline="") as handle:
    EXPECTED = tuple(
        {
            name: float(value)
            for name, value in row.items()
            if name != "input_index"
        }
        for row in csv.DictReader(handle)
    )


def _environment() -> dict[str, Any]:
    return {
        "source_root": SOURCE_ROOT,
        "bash_executable": Path("/bin/bash"),
        "perl_executable": Path("/usr/bin/perl"),
        "resolved_runtime_fingerprint": (
            configured_protein_sol_runtime_fingerprint()
        ),
    }


def _decode_output(catalog: Any, output: dict[str, Any]) -> Any:
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": port_type.type_id,
                "port_type_version": port_type.version,
                "value": output["values"][0],
            }
        )
    )


def test_local_protein_sol_golden_multiple_metrics(
    tmp_path: Path,
) -> None:
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    required = (
        SOURCE_ROOT,
        Path("/bin/bash"),
        Path("/usr/bin/perl"),
    )
    assert all(path.exists() for path in required), (
        "required locked Protein-Sol source or runtime is unavailable"
    )
    readiness = protein_sol_readiness(_environment())
    assert readiness.passing is True, readiness

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("model-backed Protein-Sol")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="source",
                    node_type_id=(
                        "contract_test.folding_sequence_batch_source"
                    ),
                    node_type_version="2.1.0",
                    binding_id=(
                        "contract_test.folding_sequence_batch_source.direct"
                    ),
                    binding_version="2.1.0",
                    node_parameters={"sequences": list(SEQUENCES)},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="score",
                    node_type_id="solubility.score_sequence",
                    node_type_version="2.1.0",
                    binding_id="solubility.protein_sol.local",
                    binding_version="2.1.0",
                    node_parameters={},
                    binding_parameters={},
                ),
            ),
            edges=(
                WorkflowEdge(
                    "source",
                    "sequence_candidates",
                    "score",
                    "sequence_candidates",
                ),
            ),
            contract_lock=(),
        ),
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    fingerprint = configured_protein_sol_runtime_fingerprint()
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                ("solubility.protein_sol.local", "2.1.0"): {
                    "values": _environment(),
                    "safe_fingerprint": fingerprint,
                    "invalidation_token": fingerprint,
                }
            }
        ),
    )
    try:
        receipt = service.start(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="model-backed-protein-sol",
        )
        wait_for_service_run_terminal_events(
            service,
            project.id,
            receipt["run_id"],
            timeout_seconds=30,
        )
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded", projection
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "score"
    )
    scores = _decode_output(catalog, output)
    source_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "source"
    )
    source_candidates = _decode_output(catalog, source_output)
    candidate_ids = [
        candidate.candidate_id for candidate in source_candidates.items
    ]
    assert len(candidate_ids) == len(SEQUENCES) == len(EXPECTED) == 2
    assert [entry.candidate_id for entry in scores.entries] == [
        candidate_id
        for candidate_id in candidate_ids
        for _ in range(3)
    ]
    assert {
        candidate_id: {
            entry.metric.contract_id: entry.value
            for entry in scores.entries
            if entry.candidate_id == candidate_id
        }
        for candidate_id in candidate_ids
    } == {
        candidate_id: {
            "solubility.protein_sol_percent": expected["percent-sol"],
            "solubility.protein_sol_scaled": expected["scaled-sol"],
            "solubility.protein_sol_pi": expected["pI"],
        }
        for candidate_id, expected in zip(
            candidate_ids,
            EXPECTED,
            strict=True,
        )
    }
    calibrated = [
        entry
        for entry in scores.entries
        if entry.metric.contract_id != "solubility.protein_sol_pi"
    ]
    assert {
        (
            entry.candidate_id,
            entry.context.calibration_metric,
            entry.context.calibration_value,
            entry.context.calibration_unit,
            entry.context.population_id,
        )
        for entry in calibrated
    } == {
        (
            candidate_id,
            "population_scaled_solubility",
            expected["population-sol"],
            "dimensionless",
            "niwa_non_membrane_2396",
        )
        for candidate_id, expected in zip(
            candidate_ids,
            EXPECTED,
            strict=True,
        )
    }
    assert all(
        entry.context.to_public() == {"kind": "intrinsic"}
        for entry in scores.entries
        if entry.metric.contract_id == "solubility.protein_sol_pi"
    )
    assert {
        entry.method.contract_id for entry in scores.entries
    } == {"solubility.protein_sol.sequence_prediction_2017"}
    binding = catalog.require_contract(
        "binding",
        "solubility.protein_sol.local",
        "2.1.0",
    )
    assert binding.descriptor["method"]["contract_id"] == (
        "solubility.protein_sol.sequence_prediction_2017"
    )
    assert binding.descriptor["implementation_identity"][
        "source_files_sha256"
    ] == binding.descriptor["readiness_declaration"]["prerequisites"][
        "source_files_sha256"
    ]
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "protein-sol.sequence-prediction-2017/"
        )
    ]
    assert len(started) == 1
    assert started[0]["engine_identity"].endswith(fingerprint)
    terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] == started[0]["invocation_id"]
    ]
    assert [event["status"] for event in terminal] == ["succeeded"]
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "solubility.protein_sol.local"
        and event["event"]["binding"]["contract_version"] == "2.1.0"
        and event["event"]["conclusion"] == "passing"
    )
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] == started[0]
    )
    assert readiness_index < invocation_index
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]
