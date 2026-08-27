"""Exact local Protein-Sol inference through the public V2 Run seam."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

import csv
import os
from pathlib import Path
from typing import Any

import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.port_contract import observation_context_canonical
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from tests.acceptance.retained_evidence import retain_service_run
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events


pytestmark = [pytest.mark.acceptance, pytest.mark.local_provider]

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


def _trusted_source_root() -> Path:
    configured = os.environ.get("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT")
    assert configured is not None, (
        "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT must select the trusted "
        "Protein-Sol source root"
    )
    root = Path(configured).expanduser()
    assert root.is_absolute()
    return root.resolve()


def _environment() -> dict[str, Any]:
    from protein_workbench_public.provider_environment import (
        provider_environment_configuration,
    )

    return provider_environment_configuration(
        {
            "PATH": os.environ.get("PATH", ""),
            "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT": str(_trusted_source_root()),
        }
    )["solubility.protein_sol.local"]


def _decode_output(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def test_local_protein_sol_golden_multiple_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.protein_sol as adapter
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    recorded: list[dict[str, Any]] = []
    original_run_process = adapter._run_local_process

    def record_and_delegate(**kwargs: Any) -> int:
        record = {
            "command": tuple(kwargs["command"]),
            "input_fasta": Path(kwargs["command"][2]).read_text(
                encoding="ascii"
            ),
        }
        return_code = original_run_process(**kwargs)
        record["raw_output"] = (
            kwargs["staging_directory"] / "seq_prediction.txt"
        ).read_bytes()
        recorded.append(record)
        return return_code

    monkeypatch.setattr(adapter, "_run_local_process", record_and_delegate)

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("model-backed Protein-Sol")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="source",
                    node_type_id=(
                        "contract_test.folding_sequence_batch_source"
                    ),
                    binding_id=(
                        "contract_test.folding_sequence_batch_source.direct"
                    ),
                    node_parameters={"sequences": list(SEQUENCES)},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="score",
                    node_type_id="solubility.score_sequence",
                    binding_id="solubility.protein_sol.local",
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
            )),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(
                catalog,
                {
                    "solubility.protein_sol.local": _environment()
                },
            ),
            result_store(projects),
        ),
        result_store(projects),
    )
    try:
        receipt = service.start(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="model-backed-protein-sol",
        )
        wait_for_service_run_terminal_events(
            service,
            project.id,
            receipt["run_id"],
            timeout_seconds=30,
        )
        projection = public_run_projection(service, project.id, receipt["run_id"])
        events = public_run_events(service, project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded", projection
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "score"
    )
    scores = _decode_output(catalog, service, projection, output)
    source_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "source"
    )
    source_candidates = _decode_output(
        catalog,
        service,
        projection,
        source_output,
    )
    candidate_ids = [
        candidate.candidate_id for candidate in source_candidates.items
    ]
    assert len(candidate_ids) == len(SEQUENCES) == len(EXPECTED) == 2
    assert len(recorded) == 1
    assert recorded[0]["command"][0] == str(_environment()["bash_executable"])
    assert recorded[0]["command"][1] == str(
        _environment()["source_root"] / "multiple_prediction_wrapper_export.sh"
    )
    assert Path(recorded[0]["command"][2]).name == "input.fasta"
    assert recorded[0]["input_fasta"] == "".join(
        f">candidate_{index}\n{sequence}\n"
        for index, sequence in enumerate(SEQUENCES)
    )
    references_by_candidate_id = {
        entry.candidate_id: entry.subject for entry in scores.entries
    }
    staged_subjects = {
        f"candidate_{index}": references_by_candidate_id[candidate_id]
        for index, candidate_id in enumerate(candidate_ids)
    }
    assert adapter.parse_protein_sol_output(
        recorded[0]["raw_output"],
        staged_subjects=staged_subjects,
    ) == tuple(
        adapter.ProteinSolPrediction(
            subject=staged_subjects[f"candidate_{index}"],
            percent_soluble_fraction=expected["percent-sol"],
            scaled_soluble_fraction=expected["scaled-sol"],
            isoelectric_point=expected["pI"],
        )
        for index, expected in enumerate(EXPECTED)
    )
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
            adapter.PROTEIN_SOL_POPULATION_SCALED,
            "dimensionless",
            "niwa_non_membrane_2396",
        )
        for candidate_id in candidate_ids
    }
    assert all(
        observation_context_canonical(entry.context) == {"kind": "intrinsic"}
        for entry in scores.entries
        if entry.metric.contract_id == "solubility.protein_sol_pi"
    )
    assert {
        entry.method.contract_id for entry in scores.entries
    } == {"solubility.protein_sol.sequence_prediction_2017"}
    binding = catalog.require_contract(
        "binding",
        "solubility.protein_sol.local")
    assert binding.descriptor["method"]["contract_id"] == (
        "solubility.protein_sol.sequence_prediction_2017"
    )
    method = catalog.require_contract(
        "method",
        "solubility.protein_sol.sequence_prediction_2017")
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"] == method.contract_id
    ]
    assert len(started) == 1
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
    retain_service_run(
        "protein-sol",
        service=service,
        projection=projection,
        events=events,
    )
