"""Required source-bound heavy acceptance for the v2 SimpleFold Binding."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
)
from core.workflow_v2 import WorkflowEdge
from datatypes import ScoreCollection
from tests.acceptance.conftest import require_ready


SEQUENCE_3GB1 = (
    "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
)


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_simplefold_v2_folds_3gb1_through_exact_binding(
    readiness: dict[str, bool],
    tmp_path: Path,
) -> None:
    """Execute the exact v2 Binding; skips are forbidden by its full gate."""
    require_ready("simplefold", readiness)
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_adapter import (
        SIMPLEFOLD_DEVICE,
        configured_runtime_fingerprint,
        provider_identity,
    )
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="3.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="3.0.0",
        node_parameters={"sequence": SEQUENCE_3GB1},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        node_type_version="6.0.0",
        binding_id="folding.fold.simplefold_local",
        binding_version="7.0.0",
        node_parameters={"effective_seed": 1603, "num_samples": 1},
        binding_parameters={"num_steps": 10},
    )
    materialize = WorkflowNodeInstance(
        node_id="materialize-confidence",
        node_type_id="structure_prediction.materialize_confidence",
        node_type_version="1.0.0",
        binding_id="structure_prediction.materialize_confidence.direct",
        binding_version="1.0.0",
        node_parameters={},
        binding_parameters={},
    )
    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("SimpleFold v2 3GB1")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(source, fold, materialize),
        edges=(
            WorkflowEdge(
                "source",
                "sequence_candidates",
                "fold",
                "sequence_candidates",
            ),
            WorkflowEdge(
                "fold",
                "structure_candidates",
                "materialize-confidence",
                "structure_candidates",
            ),
            WorkflowEdge(
                "fold",
                "confidence_facts",
                "materialize-confidence",
                "confidence_facts",
            ),
        ),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )
    fingerprint = configured_runtime_fingerprint()
    environment = EnvironmentConfiguration({
        ("folding.fold.simplefold_local", "7.0.0"): {
            "values": {
                "model_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"]
                ),
                "esm2_source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"]
                ),
                "esm2_model_root": Path(
                    os.environ[
                        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
                    ]
                ),
                "device": SIMPLEFOLD_DEVICE,
                "resolved_runtime_fingerprint": fingerprint,
            },
            "safe_fingerprint": fingerprint,
            "invalidation_token": fingerprint,
        }
    })
    service = V2RunService(projects, catalog, authoring, environment)
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="simplefold-v2-heavy",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
    }
    assert {
        "structure_candidates",
        "confidence_facts",
    } == set(outputs)
    structure_output = outputs["structure_candidates"]
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    structures = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        structure_output,
    )
    observation_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "materialize-confidence"
        and output["output_port"] == "observations"
    )
    observations = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        observation_output,
    )
    assert type(observations) is ScoreCollection
    assert {
        entry.metric.contract_id for entry in observations.entries
    } == {
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
    }
    assert {
        entry.subject.candidate_id for entry in observations.entries
    } == {structures.items[0].candidate_id}
    structure_codec = catalog.require_port_type(
        "protein.structure",
        "4.0.0",
    )
    assert {
        entry.subject.content_digest for entry in observations.entries
    } == {structure_codec.content_digest(structures.items[0].data)}
    assert all(
        entry.residue_axis is not None
        and entry.residue_axis.axis_kind == "prediction_input"
        and entry.residue_axis.layout.length == len(SEQUENCE_3GB1)
        for entry in observations.entries
    )
    binding = catalog.require_contract(
        "binding",
        "folding.fold.simplefold_local",
        "7.0.0",
    )
    assert binding.descriptor["method"]["contract_id"] == (
        "folding.fold.simplefold_100m_c7a5570"
    )
    method_ref = binding.descriptor["method"]
    method = catalog.require_contract(
        "method",
        method_ref["contract_id"],
        method_ref["contract_version"],
    )
    identity = provider_identity()
    prerequisites = binding.descriptor["readiness_declaration"][
        "prerequisites"
    ]
    assert prerequisites["simplefold_models"]["artifact_sha256"] == (
        identity["artifact_sha256"]
    )
    assert prerequisites["esm2_models"]["artifact_sha256"] == (
        identity["esm2_artifact_sha256"]
    )
    public_evidence = json.dumps(
        {"projection": projection, "events": events}
    )
    assert all(
        fragment not in public_evidence
        for fragment in (
            os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"],
            os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"],
            os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"],
        )
    )
    invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and any(
            started["event"]["type"] == "engine_invocation_started"
            and started["event"]["invocation_id"]
            == event["event"]["invocation_id"]
            and started["event"]["engine_role"] == "fold_parent_0"
            for started in events
        )
    ]
    assert len(invocations) == 1
    assert invocations[0]["status"] == "succeeded"
    started = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["invocation_id"] == invocations[0]["invocation_id"]
    )
    assert started["engine_identity"] == method.contract_digest
    randomness = started["invocation_provenance"]["effective_randomness"]
    assert randomness["control"] == "exact_seed"
    assert type(
        randomness["effective_seed"]
    ) is int
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.simplefold_local"
        and event["event"]["binding"]["contract_version"] == "7.0.0"
        and event["event"]["conclusion"] == "passing"
    )
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] == started
    )
    assert readiness_index < invocation_index
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]
