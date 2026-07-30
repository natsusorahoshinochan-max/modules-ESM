"""Required real-model gate for ProteinMPNN v2 scoring and sibling design."""

from __future__ import annotations

import os
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
from datatypes import (
    CandidateCollection,
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from modules.proteinmpnn.v2_adapter import configured_runtime_fingerprint


def _source_node() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.proteinmpnn_3gb1_structure",
        node_type_version="2.0.0",
        binding_id=(
            "contract_test.proteinmpnn_3gb1_structure.direct"
        ),
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
    )


def _environment(binding_id: str) -> EnvironmentConfiguration:
    fingerprint = configured_runtime_fingerprint()
    return EnvironmentConfiguration({
        (binding_id, "2.0.0"): {
            "values": {
                "device": "cpu",
                "resolved_runtime_fingerprint": fingerprint,
                "provider_root": Path(
                    os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
                ).resolve(),
            },
            "safe_fingerprint": fingerprint,
            "invalidation_token": fingerprint,
        }
    })


def _run(
    tmp_path: Path,
    *,
    nodes: tuple[WorkflowNodeInstance, ...],
    edges: tuple[WorkflowEdge, ...],
    binding_id: str,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_model_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("ProteinMPNN v2 real-model gate")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version="2.0.0",
            workflow_id=project.id,
            nodes=nodes,
            edges=edges,
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
    service = V2RunService(
        projects,
        catalog,
        authoring,
        _environment(binding_id),
    )
    receipt = service.start_background(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id=f"proteinmpnn-v2-{binding_id}",
    )
    service.shutdown()
    return (
        catalog,
        service.projection(project.id, receipt["run_id"]),
        service.public_events(project.id, receipt["run_id"]),
    )


def _decode(catalog: Any, output: dict[str, Any]) -> object:
    reference = output["port_type"]
    codec = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return codec.decode(canonical_json_bytes({
        "schema_namespace": "protein-workbench-port-value/v2",
        "port_type_id": codec.type_id,
        "port_type_version": codec.version,
        "value": output["values"][0],
    }))


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_proteinmpnn_v2_scoring_publishes_exact_native_observation(
    tmp_path: Path,
) -> None:
    nodes = (
        _source_node(),
        WorkflowNodeInstance(
            node_id="sequence-source",
            node_type_id="contract_test.proteinmpnn_3gb1_sequence",
            node_type_version="2.0.0",
            binding_id=(
                "contract_test.proteinmpnn_3gb1_sequence.direct"
            ),
            binding_version="2.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="score",
            node_type_id="proteinmpnn.score",
            node_type_version="2.0.0",
            binding_id="proteinmpnn.score.local",
            binding_version="2.0.0",
            node_parameters={},
            binding_parameters={},
        ),
    )
    edges = (
        WorkflowEdge(
            "source",
            "structure_candidates",
            "sequence-source",
            "structure_candidates",
        ),
        WorkflowEdge(
            "source",
            "structure_candidates",
            "score",
            "structure_candidates",
        ),
        WorkflowEdge(
            "sequence-source",
            "sequence_candidates",
            "score",
            "sequence_candidates",
        ),
    )
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        binding_id="proteinmpnn.score.local",
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "score"
    )
    scores = _decode(catalog, output)
    assert type(scores) is ScoreCollection
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    assert type(observation) is ScoreObservation
    assert observation.metric.contract_id == (
        "proteinmpnn.native_sequence_nll"
    )
    assert observation.method.contract_id == (
        "proteinmpnn.score.v_48_020_8907e667"
    )
    assert observation.context == IntrinsicObservationContext()
    assert type(observation.value) is float
    assert 0 <= observation.value <= 3.4028234663852886e38
    assert any(
        item["event"]["type"] == "engine_invocation_terminal"
        and item["event"]["status"] == "succeeded"
        and any(
            started["event"]["type"] == "engine_invocation_started"
            and started["event"]["invocation_id"]
            == item["event"]["invocation_id"]
            and started["event"]["engine_identity"].startswith(
                "proteinmpnn.score.local."
            )
            for started in events
        )
        for item in events
    )


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_proteinmpnn_v2_sibling_design_remains_exact_and_complete(
    tmp_path: Path,
) -> None:
    nodes = (
        _source_node(),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="2.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="2.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.1,
                "backbone_noise": 0,
            },
            binding_parameters={},
        ),
    )
    edges = (
        WorkflowEdge(
            "source",
            "structure_candidates",
            "design",
            "structure_candidates",
        ),
    )
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        binding_id="proteinmpnn.design.local",
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "design"
    )
    candidates = _decode(catalog, output)
    assert type(candidates) is CandidateCollection
    assert candidates.item_type == "protein.sequence"
    assert len(candidates.items) == 1
    assert len(candidates.items[0].data.sequence) == 56
    assert len(candidates.items[0].parent_ids) == 1
