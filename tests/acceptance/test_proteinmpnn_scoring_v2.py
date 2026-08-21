"""Required real-model gate for ProteinMPNN v2 scoring and sibling design."""

from __future__ import annotations

import hashlib
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
)
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    CandidateCollection,
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from tests.acceptance.retained_evidence import retain_service_run


def _source_node() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.proteinmpnn_3gb1_structure",
        node_type_version="4.0.0",
        binding_id=(
            "contract_test.proteinmpnn_3gb1_structure.direct"
        ),
        binding_version="4.0.0",
        node_parameters={},
        binding_parameters={},
    )


def _environment(
    binding_id: str,
    binding_version: str,
) -> EnvironmentConfiguration:
    return EnvironmentConfiguration({
        (binding_id, binding_version): {
            "values": {
                "device": "cpu",
                "provider_root": Path(
                    os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
                ).resolve(),
            },
        }
    })


def _run(
    tmp_path: Path,
    *,
    nodes: tuple[WorkflowNodeInstance, ...],
    edges: tuple[WorkflowEdge, ...],
    binding_id: str,
    binding_version: str,
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_model_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("ProteinMPNN v2 real-model gate")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=nodes,
            edges=edges,
            contract_lock=(),
        ),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        _environment(binding_id, binding_version),
    )
    receipt = service.start_background(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id=f"proteinmpnn-v2-{binding_id}",
    )
    service.shutdown()
    return (
        catalog,
        service,
        service.projection(project.id, receipt["run_id"]),
        service.public_events(project.id, receipt["run_id"]),
    )


def _decode(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> object:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _expected_3gb1_invocation_provenance() -> dict[str, Any]:
    return {
        "provider_residue_projection": {
            "position_semantics": "one_based_chain_local",
            "workbench_chain_order": ["A"],
            "provider_structure_chain_order": ["A"],
            "provider_chain_order": ["A"],
            "entries": [
                {
                    "residue_id": f"A:{position}",
                    "segment_index": 0,
                    "provider_chain_id": "A",
                    "provider_position": position,
                }
                for position in range(1, 57)
            ],
        }
    }


def _axis_resolver() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="resolve-axes",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        node_type_version="6.0.0",
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        binding_version="6.0.0",
        node_parameters={},
        binding_parameters={},
    )


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_proteinmpnn_v2_scoring_publishes_exact_native_observation(
    tmp_path: Path,
) -> None:
    nodes = (
        _source_node(),
        _axis_resolver(),
        WorkflowNodeInstance(
            node_id="sequence-source",
            node_type_id="contract_test.proteinmpnn_3gb1_sequence",
            node_type_version="4.0.0",
            binding_id=(
                "contract_test.proteinmpnn_3gb1_sequence.direct"
            ),
            binding_version="4.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="score",
            node_type_id="proteinmpnn.score",
            node_type_version="7.0.0",
            binding_id="proteinmpnn.score.local",
            binding_version="8.0.0",
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
            "resolve-axes",
            "structure_candidates",
        ),
        WorkflowEdge(
            "source",
            "structure_candidates",
            "score",
            "structure_candidates",
        ),
        WorkflowEdge(
            "resolve-axes",
            "residue_axes",
            "score",
            "structure_residue_axes",
        ),
        WorkflowEdge(
            "sequence-source",
            "sequence_candidates",
            "score",
            "sequence_candidates",
        ),
    )
    catalog, service, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        binding_id="proteinmpnn.score.local",
        binding_version="8.0.0",
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "score"
    )
    scores = _decode(catalog, service, projection, output)
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
    assert observation.value == 1.385357141494751
    invocation = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "engine_invocation_started"
        and item["event"]["engine_identity"]
        == observation.method.contract_digest
    )
    assert invocation["engine_role"] == "score_subject"
    assert invocation["invocation_provenance"] == {
        **_expected_3gb1_invocation_provenance(),
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": 42,
        },
    }
    assert any(
        item["event"]["type"] == "engine_invocation_terminal"
        and item["event"]["status"] == "succeeded"
        and invocation["invocation_id"] == item["event"]["invocation_id"]
        for item in events
    )
    retain_service_run(
        "proteinmpnn-native-score",
        catalog=catalog,
        service=service,
        projection=projection,
        events=events,
    )


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_proteinmpnn_v2_sibling_design_remains_exact_and_complete(
    tmp_path: Path,
) -> None:
    nodes = (
        _source_node(),
        _axis_resolver(),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="10.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="11.0.0",
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
            "resolve-axes",
            "structure_candidates",
        ),
        WorkflowEdge(
            "source",
            "structure_candidates",
            "design",
            "structure_candidates",
        ),
        WorkflowEdge(
            "resolve-axes",
            "residue_axes",
            "design",
            "structure_residue_axes",
        ),
    )
    catalog, service, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        binding_id="proteinmpnn.design.local",
        binding_version="11.0.0",
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "design"
    )
    candidates = _decode(catalog, service, projection, output)
    assert type(candidates) is CandidateCollection
    assert candidates.item_type == "protein.sequence"
    assert len(candidates.items) == 1
    candidate = candidates.items[0]
    assert hashlib.sha256(
        candidate.data.sequence.encode()
    ).hexdigest() == (
        "b89c0a40b93d8b5cbfffd0b39d219a2b01703898e9956a3e893ba7ac02ec9eea"
    )
    assert candidate.metadata["effective_call_seed"] == 4484333622234277
    assert "model" not in candidate.metadata
    assert "residue_identity_mapping" not in candidate.metadata
    assert candidate.data.residue_ids == tuple(
        f"A:{position}" for position in range(1, 57)
    )
    invocation = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "engine_invocation_started"
        and item["event"]["engine_role"] == "design_parent_0"
    )
    assert invocation["invocation_provenance"] == (
        {
            **_expected_3gb1_invocation_provenance(),
            "effective_randomness": {
                "control": "exact_seed",
                "effective_seed": candidate.metadata[
                    "effective_call_seed"
                ],
            },
        }
    )
    source_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "source"
    )
    source_candidates = _decode(
        catalog,
        service,
        projection,
        source_output,
    )
    assert type(source_candidates) is CandidateCollection
    assert candidate.parent_ids == (
        source_candidates.items[0].candidate_id,
    )
    retain_service_run(
        "proteinmpnn-sibling-design",
        catalog=catalog,
        service=service,
        projection=projection,
        events=events,
    )
