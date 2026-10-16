"""Shared 1PGA relationship oracle; controlled and real execution remain separate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from datatypes.candidate import CandidateCollection
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import CandidateRelation
from modules.structure_comparison.contracts import (
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    SIMPLEFOLD_FOLD_METHOD_REFERENCE,
    THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from modules.structure_comparison.domain import ThreeWayConsistencyEvidence


def _decode(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> tuple[Any, ...]:
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == node_id and item["output_port"] == output_port
    )
    codec = catalog.require_port_type(
        output["port_type"]["contract_id"])
    return tuple(
        codec.decode(
            service.typed_value(
                projection["project_id"],
                projection["run_id"],
                node_id,
                output_port,
                value_index,
            )[1]
        )
        for value_index in range(output["value_count"])
    )


def _one(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    values = _decode(
        service,
        catalog,
        projection,
        node_id,
        output_port,
    )
    assert len(values) == 1
    return values[0]


def _assert_live_node_contracts(
    catalog: Any,
    workflow: Mapping[str, Any],
    messages: tuple[dict[str, Any], ...],
    projection: dict[str, Any],
    expected: dict[str, tuple[int, str | None]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    nodes = {node["node_id"]: node for node in workflow["nodes"]}
    events = tuple(message["event"] for message in messages)
    node_by_attempt = {
        event["node_attempt_id"]: event["node_id"]
        for event in events
        if event["type"] == "node_attempt_started"
    }
    node_by_operation = {
        event["operation_attempt_id"]: node_by_attempt[
            event["node_attempt_id"]
        ]
        for event in events
        if event["type"] == "operation_attempt_started"
    }
    terminal_by_invocation = {
        event["invocation_id"]: event
        for event in events
        if event["type"] == "engine_invocation_terminal"
    }
    dispositions = {
        item["node_id"]: item for item in projection["node_dispositions"]
    }
    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for node_id, (expected_count, randomness_control) in expected.items():
        node = nodes[node_id]
        binding = catalog.require_contract(
            "binding",
            node["binding_id"])
        assert dispositions[node_id]["outcome"] == "succeeded"
        assert dispositions[node_id]["resolution"] == "executed"
        assert any(
            event["type"] == "readiness_attested"
            and event["binding"] == binding.reference()
            and event["conclusion"] == "passing"
            for event in events
        )
        invocations = tuple(
            event
            for event in events
            if event["type"] == "engine_invocation_started"
            and node_by_operation[event["operation_attempt_id"]] == node_id
        )
        assert len(invocations) == expected_count
        assert all(
            invocation["engine_identity"]
            == binding.descriptor["method"]["contract_id"]
            and terminal_by_invocation[invocation["invocation_id"]]["status"]
            == "succeeded"
            for invocation in invocations
        )
        if randomness_control is None:
            assert all(
                "invocation_provenance" not in invocation
                for invocation in invocations
            )
        else:
            assert all(
                invocation["invocation_provenance"][
                    "effective_randomness"
                ]["control"]
                == randomness_control
                for invocation in invocations
            )
        result[node_id] = invocations
    return result


def _assert_1pga_science(
    service: Any,
    catalog: Any,
    workflow: Mapping[str, Any],
    events: tuple[dict[str, Any], ...],
    projection: dict[str, Any],
    *,
    local_models: bool,
) -> None:
    live_invocations = _assert_live_node_contracts(
        catalog,
        workflow,
        events,
        projection,
        {
            "fold-esmfold2": (
                1,
                "exact_seed" if local_models else "provider_uncontrolled",
            ),
        },
    )
    event_facts = tuple(message["event"] for message in events)
    simplefold_binding = catalog.require_contract(
        "binding",
        "folding.fold.simplefold_local",
    )
    simplefold_disposition = next(
        disposition
        for disposition in projection["node_dispositions"]
        if disposition["node_id"] == "fold-simplefold"
    )
    assert simplefold_disposition["outcome"] == "succeeded"
    assert simplefold_disposition["resolution"] == "executed"
    assert any(
        event["type"] == "readiness_attested"
        and event["binding"] == simplefold_binding.reference()
        and event["conclusion"] == "passing"
        for event in event_facts
    )
    simplefold_node_attempt_ids = {
        event["node_attempt_id"]
        for event in event_facts
        if event["type"] == "node_attempt_started"
        and event["node_id"] == "fold-simplefold"
    }
    simplefold_operation_attempt_ids = {
        event["operation_attempt_id"]
        for event in event_facts
        if event["type"] == "operation_attempt_started"
        and event["node_attempt_id"] in simplefold_node_attempt_ids
    }
    simplefold_invocations = tuple(
        event
        for event in event_facts
        if event["type"] == "engine_invocation_started"
        and event["operation_attempt_id"]
        in simplefold_operation_attempt_ids
    )
    assert [
        invocation["engine_role"]
        for invocation in simplefold_invocations
    ] == ["fold_parent_0_esm2_features", "fold_parent_0"]
    terminal_by_invocation = {
        event["invocation_id"]: event
        for event in event_facts
        if event["type"] == "engine_invocation_terminal"
    }
    assert all(
        invocation["engine_identity"]
        == simplefold_binding.descriptor["method"]["contract_id"]
        and terminal_by_invocation[invocation["invocation_id"]]["status"]
        == "succeeded"
        for invocation in simplefold_invocations
    )
    feature_invocation, folding_invocation = simplefold_invocations
    assert "invocation_provenance" not in feature_invocation
    assert folding_invocation["invocation_provenance"][
        "effective_randomness"
    ]["control"] == "exact_seed"
    workflow_nodes = {node["node_id"]: node for node in workflow["nodes"]}
    assert workflow_nodes["fold-esmfold2"]["node_parameters"] == {
        "effective_seed": 1075001,
        "num_samples": 1,
    }
    assert workflow_nodes["fold-simplefold"]["node_parameters"] == {
        "effective_seed": 1075002,
        "num_samples": 1,
    }
    assert workflow_nodes["fold-simplefold"]["binding_parameters"] == {
        "num_steps": 50,
    }
    input_candidates = _one(
        service, catalog, projection, "import-input", "structure_candidates"
    )
    sequence = _one(
        service, catalog, projection, "extract-sequence", "sequence_candidates"
    )
    esmfold2 = _one(
        service, catalog, projection, "fold-esmfold2", "structure_candidates"
    )
    simplefold = _one(
        service, catalog, projection, "fold-simplefold", "structure_candidates"
    )
    pairing = _one(
        service, catalog, projection, "pair-methods", "relation"
    )
    consistency = _one(
        service, catalog, projection, "classify-consistency", "consistency"
    )
    assert all(
        type(value) is CandidateCollection
        for value in (input_candidates, sequence, esmfold2, simplefold)
    )
    assert len(input_candidates.items) == len(sequence.items) == 1
    assert len(esmfold2.items) == len(simplefold.items) == 1
    assert sequence.items[0].data.sequence == (
        "MKESYKVILTNKKTEKNLVLTTTQEVSNEENAHDKEKVFVEEYANKTLGNPAFTNWTYQFDATHDEWFCVVEANL"
    )
    assert sequence.items[0].parent_ids == (
        input_candidates.items[0].candidate_id,
    )
    assert type(pairing) is CandidateRelation
    assert len(pairing.entries) == 1
    assert esmfold2.items[0].parent_ids == simplefold.items[0].parent_ids == (
        sequence.items[0].candidate_id,
    )
    assert "configured_base_seed" not in simplefold.items[0].metadata
    assert simplefold.items[0].metadata["num_steps"] == 50
    assert folding_invocation[
        "invocation_provenance"
    ]["effective_randomness"]["effective_seed"] == (
        simplefold.items[0].metadata["effective_call_seed"]
    )
    assert pairing.entries[0].subject.candidate_id == (
        esmfold2.items[0].candidate_id
    )
    assert pairing.entries[0].reference.candidate_id == (
        simplefold.items[0].candidate_id
    )
    assert type(consistency) is ThreeWayConsistencyEvidence
    assert consistency.classification in {
        "three_way_consistent",
        "method_disagreement",
        "input_disagreement",
        "all_disagree",
        "insufficient_evidence",
    }
    assert consistency.input_b_factor_semantics == (
        "uninterpreted_coordinate_temperature_factor"
    )
    assert consistency.residue_count == 75
    assert (
        consistency.plddt_threshold,
        consistency.tm_score_threshold,
        consistency.rmsd_threshold_angstrom,
    ) == (70.0, 0.80, 2.50)
    assert consistency.classification_method == (
        THREE_WAY_CONSISTENCY_METHOD_REFERENCE
    )
    assert len(consistency.edges) == 3
    assert len(consistency.confidences) == 2
    esmfold2_node = workflow_nodes["fold-esmfold2"]
    esmfold2_binding = catalog.require_contract(
        "binding",
        esmfold2_node["binding_id"])
    esmfold2_method = catalog.require_contract(
        "method",
        esmfold2_binding.descriptor["method"]["contract_id"])
    assert tuple(item.method for item in consistency.confidences) == (
        ExactContractReference(**esmfold2_method.reference()),
        SIMPLEFOLD_FOLD_METHOD_REFERENCE,
    )
    assert all(
        item.eligible == (item.mean_residue_plddt >= 70.0)
        for item in consistency.confidences
    )
    assert [edge.edge_id for edge in consistency.edges] == [
        "input_esmfold2",
        "input_simplefold",
        "esmfold2_simplefold",
    ]
    assert all(
        edge.normalization_length == 75
        and edge.aligned_atom_count == 75
        and edge.alignment_method
        == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
        and edge.tm_score_method == TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE
        and edge.rmsd_method == RMSD_FROM_EVIDENCE_METHOD_REFERENCE
        and edge.close
        == (edge.tm_score >= 0.80 and edge.rmsd_angstrom <= 2.50)
        for edge in consistency.edges
    )
