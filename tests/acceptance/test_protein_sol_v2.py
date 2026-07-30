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
SEQUENCE = "".join(
    line.strip()
    for line in (FIXTURE_ROOT / "protein_sol_input.fasta").read_text().splitlines()
    if not line.startswith(">")
)
with (FIXTURE_ROOT / "protein_sol_expected.csv").open(newline="") as handle:
    EXPECTED = {
        name: float(value)
        for name, value in next(csv.DictReader(handle)).items()
    }


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
            schema_version="2.0.0",
            workflow_id=project.id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="source",
                    node_type_id="contract_test.folding_sequence_source",
                    node_type_version="2.0.0",
                    binding_id=(
                        "contract_test.folding_sequence_source.direct"
                    ),
                    binding_version="2.0.0",
                    node_parameters={"sequence": SEQUENCE},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="score",
                    node_type_id="solubility.score_sequence",
                    node_type_version="2.0.0",
                    binding_id="solubility.protein_sol.local",
                    binding_version="2.0.0",
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
                ("solubility.protein_sol.local", "2.0.0"): {
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
    assert {
        entry.metric.contract_id: entry.value
        for entry in scores.entries
    } == {
        "solubility.protein_sol_percent": EXPECTED["percent-sol"],
        "solubility.protein_sol_scaled": EXPECTED["scaled-sol"],
        "solubility.protein_sol_pi": EXPECTED["pI"],
    }
    calibrated = [
        entry
        for entry in scores.entries
        if entry.metric.contract_id != "solubility.protein_sol_pi"
    ]
    assert {
        entry.context.calibration_value for entry in calibrated
    } == {EXPECTED["population-sol"]}
    pi = next(
        entry
        for entry in scores.entries
        if entry.metric.contract_id == "solubility.protein_sol_pi"
    )
    assert pi.context.to_public() == {"kind": "intrinsic"}
    assert {
        entry.method.contract_id for entry in scores.entries
    } == {"solubility.protein_sol.sequence_prediction_2017"}
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
