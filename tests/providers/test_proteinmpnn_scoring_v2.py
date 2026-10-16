"""Required real-model gate for ProteinMPNN v2 scoring and sibling design."""

from __future__ import annotations

from tests.scenarios.proteinmpnn_real import (
    _axis_resolver,
    _decode,
    _environment,
    _run,
)

from core.catalog.authoring import AuthoringCapabilityProjection

from tests.support.ledger import public_run_events, public_run_projection

import os
from pathlib import Path
from typing import Any

import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
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
from datatypes.candidate import CandidateCollection
from datatypes.observation import (
    PairwiseObservationContext,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
)
from tests.providers.retained_evidence import retain_service_run


def _source_node() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.proteinmpnn_3gb1_structure",
        binding_id=(
            "contract_test.proteinmpnn_3gb1_structure.direct"
        ),
        node_parameters={},
        binding_parameters={},
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
            binding_id=(
                "contract_test.proteinmpnn_3gb1_sequence.direct"
            ),
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="score",
            node_type_id="proteinmpnn.score",
            binding_id="proteinmpnn.score.local",
            node_parameters={},
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
        binding_id="proteinmpnn.score.local")

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "score"
    )
    scores = _decode(catalog, service, projection, output)
    sequence_output = next(
        item for item in projection["outputs"] if item["node_id"] == "sequence-source"
    )
    subjects = _decode(catalog, service, projection, sequence_output)
    assert subjects.items[0].parent_ids == ()
    assert subjects.items[0].data.residue_ids is None
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
    assert observation.context == PairwiseObservationContext(
        PairwiseParticipant("subject", observation.subject),
        PairwiseParticipant("reference", observation.residue_axis.source),
        "fixed_reference", "provider_masked_mean",
    )
    invocation = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "engine_invocation_started"
        and item["event"]["engine_identity"]
        == observation.method.contract_id
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
            binding_id="proteinmpnn.design.local",
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
        binding_id="proteinmpnn.design.local")

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
        service=service,
        projection=projection,
        events=events,
    )
