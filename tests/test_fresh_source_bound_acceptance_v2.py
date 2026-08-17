"""Fresh installed 1PGA, 2EMO, and 5G53 public evidence contracts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

import pytest

from core import build_discovered_frozen_catalog
from datatypes import (
    CandidateCollection,
    CandidateDataReference,
    PairwiseCandidateMapping,
    ScoreCollection,
)
from modules.structure_comparison.contracts import (
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    SIMPLEFOLD_FOLD_METHOD_REFERENCE,
    THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from modules.structure_comparison.domain import (
    InsertedLoopEvaluationCollection,
    StructureAlignmentEvidence,
    ThreeWayConsistencyEvidence,
)
from modules.structure_transform import (
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociations,
)
from protein_workbench_public import (
    bundle_digest,
    validate_event,
    validate_response,
)
from tests.test_installed_backend_v2 import InstalledArtifact, installed_artifact


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = {
    "fresh-1pga": {
        "input": PROJECT_ROOT / "pdbs" / "1PGA-75-gen1_0690.pdb",
        "input_digest": (
            "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
        ),
        "workflow": PROJECT_ROOT / "examples/v2/source-bound-1pga.workflow.json",
        "required_environment": (
            "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
        ),
    },
    "fresh-2emo": {
        "input": PROJECT_ROOT / "pdbs" / "2EMO.pdb",
        "input_digest": (
            "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
        ),
        "workflow": PROJECT_ROOT / "examples/v2/source-bound-2emo.workflow.json",
        "required_environment": (
            "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
            "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",
        ),
    },
    "fresh-5g53": {
        "input": PROJECT_ROOT / "pdbs" / "5G53.pdb",
        "input_digest": (
            "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
        ),
        "workflow": PROJECT_ROOT / "examples/v2/source-bound-5g53.workflow.json",
        "required_environment": (),
    },
}


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load(root: Path, name: str) -> Any:
    return json.loads((root / name).read_bytes())


def _decode(
    root: Path,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> tuple[Any, ...]:
    catalog = build_discovered_frozen_catalog()
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == node_id and item["output_port"] == output_port
    )
    codec = catalog.require_port_type(
        output["port_type"]["contract_id"],
        output["port_type"]["contract_version"],
    )
    inventory = _load(root, "typed-values.json")
    records = sorted(
        (
            item
            for item in inventory
            if item["node_id"] == node_id
            and item["output_port"] == output_port
        ),
        key=lambda item: item["value_index"],
    )
    return tuple(
        codec.decode((root / item["bundle_path"]).read_bytes())
        for item in records
    )


def _one(
    root: Path,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    values = _decode(root, projection, node_id, output_port)
    assert len(values) == 1
    return values[0]


def _assert_live_node_contracts(
    root: Path,
    projection: dict[str, Any],
    expected: dict[str, tuple[int, str | None]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    catalog = build_discovered_frozen_catalog()
    workflow = _load(root, "workflow.json")
    nodes = {node["node_id"]: node for node in workflow["nodes"]}
    messages = _load(root, "events.json")
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
            node["binding_id"],
            node["binding_version"],
        )
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
            == binding.descriptor["method"]["contract_digest"]
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


def _assert_common_bundle(root: Path, tier_name: str) -> dict[str, Any]:
    contract = CONTRACTS[tier_name]
    receipt = _load(root, "source-bound-receipt.json")
    projection = _load(root, "run-projection.json")
    events = _load(root, "events.json")
    values = _load(root, "typed-values.json")
    artifacts = _load(root, "artifacts.json")
    catalog = build_discovered_frozen_catalog()

    assert receipt["schema_namespace"] == (
        "protein-workbench-source-bound-evidence/v1"
    )
    assert receipt["tier"] == tier_name
    assert receipt["input_content_digest"] == (
        "sha256:" + contract["input_digest"]
    )
    assert receipt["protocol_digest"] == bundle_digest()
    assert receipt["catalog_contract_digest"] == catalog.contract_digest
    assert receipt["status"] == "succeeded"
    assert _digest(contract["input"]) == (
        "sha256:" + contract["input_digest"]
    )
    assert receipt["workflow_content_digest"] == _digest(contract["workflow"])
    if tier_name == "fresh-2emo":
        assert _load(root, "model-lifecycle.json") == {
            "model": "proteinmpnn",
            "load_count": 1,
            "release": "before-protein-sol",
        }
    assert projection["status"] == "succeeded"
    validate_response("run_projection", 200, projection)
    assert all(
        disposition["outcome"] == "succeeded"
        for disposition in projection["node_dispositions"]
    )
    assert all("values" not in output for output in projection["outputs"])
    assert "values" not in json.dumps(events)
    assert events[-1]["event"] == {"type": "run_terminal", "status": "succeeded"}
    for event in events:
        validate_event(event)
    assert [event["sequence"] for event in events] == sorted(
        event["sequence"] for event in events
    )
    assert len(values) == sum(
        output["value_count"] for output in projection["outputs"]
    )
    for item in values:
        payload = (root / item["bundle_path"]).read_bytes()
        assert len(payload) == item["size"]
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == (
            item["value_content_digest"]
        )
    assert len(artifacts) == len(projection["artifact_index"])
    for item in artifacts:
        payload = (root / item["bundle_path"]).read_bytes()
        assert item["retrieved_content_digest"] == item["content_digest"]
        assert _digest(root / item["bundle_path"]) == item["content_digest"]
    return projection


def _assert_science(root: Path, tier_name: str, projection: dict[str, Any]) -> None:
    if tier_name == "fresh-1pga":
        live_invocations = _assert_live_node_contracts(
            root,
            projection,
            {
                "fold-esmfold2": (1, "provider_uncontrolled"),
                "fold-simplefold": (1, "exact_seed"),
            },
        )
        workflow_nodes = {
            node["node_id"]: node for node in _load(root, "workflow.json")["nodes"]
        }
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
            root, projection, "import-input", "structure_candidates"
        )
        sequence = _one(
            root, projection, "extract-sequence", "sequence_candidates"
        )
        esmfold2 = _one(
            root, projection, "fold-esmfold2", "structure_candidates"
        )
        simplefold = _one(
            root, projection, "fold-simplefold", "structure_candidates"
        )
        pairing = _one(root, projection, "pair-methods", "pairing")
        consistency = _one(
            root, projection, "classify-consistency", "consistency"
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
        assert type(pairing) is PairwiseCandidateMapping
        assert len(pairing.entries) == 1
        assert esmfold2.items[0].parent_ids == simplefold.items[0].parent_ids == (
            sequence.items[0].candidate_id,
        )
        assert simplefold.items[0].metadata["configured_base_seed"] == 1075002
        assert simplefold.items[0].metadata["num_steps"] == 50
        assert live_invocations["fold-simplefold"][0][
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
        assert tuple(item.method for item in consistency.confidences) == (
            REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
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
    elif tier_name == "fresh-2emo":
        live_invocations = _assert_live_node_contracts(
            root,
            projection,
            {
                "design-sequences": (1, "exact_seed"),
                "fold-esmfold2": (8, "provider_uncontrolled"),
                "score-protein-sol": (1, None),
            },
        )
        workflow_nodes = {
            node["node_id"]: node for node in _load(root, "workflow.json")["nodes"]
        }
        assert workflow_nodes["design-sequences"]["node_parameters"] == {
            "effective_seed": 2066001,
            "num_sequences": 8,
            "temperature": 0.1,
            "backbone_noise": 0,
        }
        assert workflow_nodes["fold-esmfold2"]["node_parameters"] == {
            "effective_seed": 2066002,
            "num_samples": 1,
        }
        normalizations = _one(
            root,
            projection,
            "materialize-reference-normalizations",
            "modified_residue_normalizations",
        )
        axes = _one(root, projection, "resolve-reference", "residue_axes")
        normalized = _one(
            root, projection, "normalize-reference", "structure_candidates"
        )
        designs = _one(
            root, projection, "design-sequences", "sequence_candidates"
        )
        folds = _one(root, projection, "fold-esmfold2", "structure_candidates")
        alignments = _decode(root, projection, "align-folds", "alignments")
        tm_scores = _one(root, projection, "score-tm", "scores")
        rmsd_scores = _one(root, projection, "score-rmsd", "scores")
        confidence = _one(
            root, projection, "materialize-confidence", "observations"
        )
        protein_sol = _one(root, projection, "score-protein-sol", "scores")
        tm_passing = _one(root, projection, "filter-tm", "candidates")
        rmsd_passing = _one(root, projection, "filter-rmsd", "candidates")
        plddt_passing = _one(root, projection, "filter-plddt", "candidates")
        solubility_passing = _one(
            root, projection, "filter-protein-sol", "candidates"
        )
        soluble_folds = _one(
            root, projection, "select-soluble-folds", "candidates"
        )
        passing = _one(
            root, projection, "passing-candidates", "candidates"
        )
        assert type(normalizations) is (
            CandidateModifiedResidueNormalizationAssociations
        )
        normalization = normalizations.entries[0].normalizations.entries[0]
        assert (
            normalization.observed_residue_id,
            normalization.parent_residue_ids,
            normalization.parent_sequence,
        ) == ("A:66", ("A:65", "A:66", "A:67"), "SHG")
        assert type(axes) is CandidateResolvedResidueAxisAssociations
        assert axes.entries[0].residue_axis.layout.length == 224
        assert axes.entries[0].residue_axis.layout.residue_ids[58:63] == (
            "A:64",
            "A:65",
            "A:66",
            "A:67",
            "A:68",
        )
        axis = axes.entries[0].residue_axis
        fixed_span = tuple(
            axis.layout.residue_ids.index(residue_id)
            for residue_id in ("A:65", "A:66", "A:67")
        )
        assert axis.sequence[fixed_span[0] : fixed_span[-1] + 1] == "SHG"
        assert all(
            type(value) is CandidateCollection
            for value in (
                normalized,
                designs,
                folds,
                tm_passing,
                rmsd_passing,
                plddt_passing,
                solubility_passing,
                soluble_folds,
                passing,
            )
        )
        assert all(
            type(value) is ScoreCollection
            for value in (tm_scores, rmsd_scores, confidence, protein_sol)
        )
        assert len(designs.items) == len(folds.items) == 8
        assert all(
            design.parent_ids == (normalized.items[0].candidate_id,)
            and design.metadata["effective_seed"] == 2066001
            and design.metadata["num_sequences"] == 8
            and design.metadata["temperature"] == 0.1
            and design.metadata["backbone_noise"] == 0.0
            and "constraint_digest" in design.metadata
            for design in designs.items
        )
        assert all(
            "".join(design.data.sequence[index] for index in fixed_span)
            == "SHG"
            for design in designs.items
        )
        assert live_invocations["design-sequences"][0][
            "invocation_provenance"
        ]["effective_randomness"]["effective_seed"] == (
            designs.items[0].metadata["effective_call_seed"]
        )
        assert tuple(
            invocation["engine_role"]
            for invocation in live_invocations["score-protein-sol"]
        ) == ("protein_sol_sequence_prediction",)
        design_ids = {design.candidate_id for design in designs.items}
        fold_ids = {fold.candidate_id for fold in folds.items}
        assert all(
            len(fold.parent_ids) == 1 and fold.parent_ids[0] in design_ids
            for fold in folds.items
        )
        assert len(alignments) == 8
        structure_port = build_discovered_frozen_catalog().require_port_type(
            "protein.structure",
            "4.0.0",
        )
        fold_references = {
            CandidateDataReference(
                fold.candidate_id,
                folds.item_type,
                structure_port.content_digest(fold.data),
            )
            for fold in folds.items
        }
        reference = normalized.items[0]
        reference_value = CandidateDataReference(
            reference.candidate_id,
            normalized.item_type,
            structure_port.content_digest(reference.data),
        )
        assert {alignment.subject for alignment in alignments} == fold_references
        assert {alignment.reference for alignment in alignments} == {
            reference_value
        }
        assert tuple(
            sorted(
                alignment.normalization.aligned_atom_count
                for alignment in alignments
            )
        ) == (216, 218, 219, 219, 221, 221, 221, 221)
        assert all(
            type(alignment) is StructureAlignmentEvidence
            and alignment.method == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
            and alignment.normalization.subject_axis_residue_count == 224
            and alignment.normalization.reference_axis_residue_count == 224
            and alignment.normalization.subject_ca_count == 224
            and alignment.normalization.reference_ca_count == 224
            and alignment.normalization.aligned_atom_count
            == len(alignment.correspondence)
            == sum(
                segment.paired_residue_count
                for segment in alignment.segment_map
            )
            for alignment in alignments
        )

        def subjects(collection: CandidateCollection) -> set[str]:
            return {item.candidate_id for item in collection.items}

        tm_by_subject = {
            observation.subject.candidate_id: observation
            for observation in tm_scores.entries
        }
        rmsd_by_subject = {
            observation.subject.candidate_id: observation
            for observation in rmsd_scores.entries
        }
        mean_plddt = {
            observation.subject.candidate_id: observation
            for observation in confidence.entries
            if observation.metric.contract_id == "structure.plddt.mean_residue"
        }
        scaled_solubility = {
            observation.subject.candidate_id: observation
            for observation in protein_sol.entries
            if observation.metric.contract_id
            == "solubility.protein_sol_scaled"
        }
        assert set(tm_by_subject) == set(rmsd_by_subject) == fold_ids
        assert set(mean_plddt) == fold_ids
        assert set(scaled_solubility) == design_ids
        assert subjects(tm_passing) == {
            subject
            for subject, observation in tm_by_subject.items()
            if float(observation.value) >= 0.80
        }
        assert subjects(rmsd_passing) == {
            subject
            for subject, observation in rmsd_by_subject.items()
            if float(observation.value) <= 2.50
        }
        assert subjects(plddt_passing) == {
            subject
            for subject, observation in mean_plddt.items()
            if float(observation.value) >= 70.0
        }
        assert subjects(solubility_passing) == {
            subject
            for subject, observation in scaled_solubility.items()
            if float(observation.value) >= 0.446
        }
        soluble_fold_ids = {
            fold.candidate_id
            for fold in folds.items
            if fold.parent_ids[0] in subjects(solubility_passing)
        }
        assert subjects(soluble_folds) == soluble_fold_ids
        assert subjects(passing) == (
            subjects(tm_passing)
            & subjects(rmsd_passing)
            & subjects(plddt_passing)
            & soluble_fold_ids
        )
        assert 0 <= len(passing.items) <= 8
    else:
        live_invocations = _assert_live_node_contracts(
            root,
            projection,
            {
                "generate-shorter-8": (4, "provider_uncontrolled"),
                "fold-shorter-8": (2, "provider_uncontrolled"),
                "generate-numbering-implied-12": (
                    4,
                    "provider_uncontrolled",
                ),
                "fold-numbering-implied-12": (2, "provider_uncontrolled"),
                "generate-longer-16": (4, "provider_uncontrolled"),
                "fold-longer-16": (2, "provider_uncontrolled"),
            },
        )
        assert live_invocations
        workflow_nodes = {
            node["node_id"]: node for node in _load(root, "workflow.json")["nodes"]
        }
        axes = _one(root, projection, "resolve-reference", "residue_axes")
        sequences = _one(root, projection, "merge-sequences", "candidates")
        counterparts = _one(
            root, projection, "merge-counterparts", "candidates"
        )
        reconstructions = _one(
            root, projection, "merge-reconstructions", "candidates"
        )
        folds = _one(root, projection, "merge-folds", "candidates")
        assert type(axes) is CandidateResolvedResidueAxisAssociations
        assert axes.entries[0].residue_axis.layout.length == 283
        residue_ids = axes.entries[0].residue_axis.layout.residue_ids
        assert residue_ids[residue_ids.index("A:146") + 1] == "A:159"
        assert residue_ids[residue_ids.index("A:211") + 1] == "A:224"
        assert all(
            type(value) is CandidateCollection
            for value in (sequences, counterparts, reconstructions, folds)
        )
        assert tuple(len(item.data.sequence) for item in sequences.items) == (
            291,
            291,
            295,
            295,
            299,
            299,
        )
        assert len(counterparts.items) == len(reconstructions.items) == len(folds.items) == 6
        accepted_fold_ids: set[str] = set()
        for branch, length in (
            ("shorter-8", 291),
            ("numbering-implied-12", 295),
            ("longer-16", 299),
        ):
            for port in (
                "confidence_facts",
                "sequence_reconstruction_confidence_facts",
            ):
                facts = _one(root, projection, f"generate-{branch}", port)
                assert len(facts.entries) == 2
                assert all(
                    fact.pae is not None
                    and len(fact.pae) == length
                    and len(fact.pae[0]) == length
                    for fact in facts.entries
                )
            branch_sequences = _one(
                root,
                projection,
                f"generate-{branch}",
                "sequence_candidates",
            )
            branch_counterparts = _one(
                root,
                projection,
                f"generate-{branch}",
                "structure_candidates",
            )
            branch_reconstructions = _one(
                root,
                projection,
                f"generate-{branch}",
                "sequence_reconstruction_candidates",
            )
            branch_pairing = _one(
                root,
                projection,
                f"generate-{branch}",
                "counterpart_pairs",
            )
            branch_folds = _one(
                root, projection, f"fold-{branch}", "structure_candidates"
            )
            assert all(
                type(value) is CandidateCollection
                for value in (
                    branch_sequences,
                    branch_counterparts,
                    branch_reconstructions,
                    branch_folds,
                )
            )
            assert type(branch_pairing) is PairwiseCandidateMapping
            assert len(branch_sequences.items) == len(branch_pairing.entries) == 2
            expected_seed = {
                "shorter-8": 5353008,
                "numbering-implied-12": 5353012,
                "longer-16": 5353016,
            }[branch]
            assert workflow_nodes[f"generate-{branch}"]["node_parameters"] == {
                "effective_seed": expected_seed,
                "num_samples": 2,
                "num_steps": 20,
                "temperature": 0.7,
                "top_p": 1.0,
                "schedule": "cosine",
                "strategy": "random",
                "temperature_annealing": True,
            }
            assert workflow_nodes[f"fold-{branch}"]["node_parameters"] == {
                "effective_seed": 5353999,
                "num_samples": 1,
            }
            expected_generation_parameters = {
                "num_steps": 20,
                "temperature": 0.7,
                "top_p": 1.0,
                "schedule": "cosine",
                "strategy": "random",
                "temperature_annealing": True,
            }
            assert all(
                sequence.metadata["requested_generation_parameters"]
                == expected_generation_parameters
                and sequence.metadata["effective_generation_parameters"]
                == {"sequence": expected_generation_parameters}
                for sequence in branch_sequences.items
            )
            assert all(
                counterpart.metadata["requested_generation_parameters"]
                == expected_generation_parameters
                and counterpart.metadata["effective_generation_parameters"]
                == {
                    "sequence": expected_generation_parameters,
                    "structure": expected_generation_parameters,
                }
                for counterpart in branch_counterparts.items
            )
            assert tuple(
                counterpart.parent_ids
                for counterpart in branch_counterparts.items
            ) == tuple(
                (sequence.candidate_id,)
                for sequence in branch_sequences.items
            )
            assert tuple(
                reconstruction.parent_ids
                for reconstruction in branch_reconstructions.items
            ) == tuple(
                (sequence.candidate_id,)
                for sequence in branch_sequences.items
            )
            assert tuple(fold.parent_ids for fold in branch_folds.items) == tuple(
                (sequence.candidate_id,) for sequence in branch_sequences.items
            )
            assert tuple(
                entry.subject.candidate_id for entry in branch_pairing.entries
            ) == tuple(
                sequence.candidate_id for sequence in branch_sequences.items
            )
            assert tuple(
                entry.reference.candidate_id for entry in branch_pairing.entries
            ) == tuple(
                counterpart.candidate_id
                for counterpart in branch_counterparts.items
            )
            confidence_facts = _one(
                root,
                projection,
                f"generate-{branch}",
                "confidence_facts",
            )
            reconstruction_confidence = _one(
                root,
                projection,
                f"generate-{branch}",
                "sequence_reconstruction_confidence_facts",
            )
            assert {
                fact.prediction_key for fact in confidence_facts.entries
            } == {
                candidate.metadata["prediction_key"]
                for candidate in branch_counterparts.items
            }
            assert {
                fact.prediction_key
                for fact in reconstruction_confidence.entries
            } == {
                candidate.metadata["prediction_key"]
                for candidate in branch_reconstructions.items
            }
            quality = _one(
                root,
                projection,
                f"evaluate-{branch}",
                "quality_evidence",
            )
            assert type(quality) is InsertedLoopEvaluationCollection
            assert len(quality.entries) == 2
            assert {
                evidence.subject.candidate_id for evidence in quality.entries
            } == {fold.candidate_id for fold in branch_folds.items}
            assert {
                evidence.counterpart.candidate_id for evidence in quality.entries
            } == {
                counterpart.candidate_id
                for counterpart in branch_counterparts.items
            }
            for evidence in quality.entries:
                assert len(evidence.resolved_core_residue_ids) == 283
                assert len(evidence.loop_residue_ids) == length - 283
                assert len(
                    evidence.prediction_to_structure_correspondence
                ) == length
                assert evidence.thresholds == type(evidence.thresholds)(
                    resolved_core_tm_score_minimum=0.75,
                    resolved_core_rmsd_angstrom_maximum=3.00,
                    counterpart_tm_score_minimum=0.70,
                    counterpart_rmsd_angstrom_maximum=3.50,
                    resolved_core_mean_plddt_minimum=70.0,
                    junction_cn_distance_angstrom_minimum=1.15,
                    junction_cn_distance_angstrom_maximum=1.55,
                    loop_core_nonbonded_distance_angstrom_minimum=2.00,
                )
                assert evidence.resolved_core_passed == (
                    evidence.resolved_core_tm_score >= 0.75
                    and evidence.resolved_core_rmsd_angstrom <= 3.00
                )
                assert evidence.counterpart_passed == (
                    evidence.counterpart_tm_score >= 0.70
                    and evidence.counterpart_rmsd_angstrom <= 3.50
                )
                assert evidence.confidence_passed == (
                    evidence.resolved_core_mean_plddt >= 70.0
                )
                assert evidence.junctions_passed == (
                    1.15
                    <= evidence.left_junction.distance_angstrom
                    <= 1.55
                    and 1.15
                    <= evidence.right_junction.distance_angstrom
                    <= 1.55
                )
                assert evidence.clash_passed == (
                    evidence.minimum_loop_core_nonbonded_distance.distance_angstrom
                    >= 2.00
                )
                assert evidence.accepted == all((
                    evidence.resolved_core_passed,
                    evidence.counterpart_passed,
                    evidence.confidence_passed,
                    evidence.junctions_passed,
                    evidence.clash_passed,
                ))
                if evidence.accepted:
                    accepted_fold_ids.add(evidence.subject.candidate_id)
        passing = _one(root, projection, "merge-passing", "candidates")
        assert type(passing) is CandidateCollection
        assert {item.candidate_id for item in passing.items} == accepted_fold_ids
        assert len(projection["artifact_index"]) == 6
        assert [
            artifact["candidate_id"]
            for artifact in projection["artifact_index"]
        ] == [fold.candidate_id for fold in folds.items]


def _run_fresh(
    tier_name: str,
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    expected_revision = os.environ["PROTEIN_WORKBENCH_FRESH_SOURCE_REVISION"]
    observed_revision = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert observed_revision == expected_revision
    assert subprocess.run(
        ["/usr/bin/git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout == ""
    evidence_root = Path(
        os.environ["PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING"]
    )
    assert evidence_root.is_dir() and not any(evidence_root.iterdir())
    for variable in (
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
        *CONTRACTS[tier_name]["required_environment"],
    ):
        configured = Path(os.environ[variable])
        assert configured.is_absolute() and configured.exists()

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(PROJECT_ROOT)
    env["PROTEIN_WORKBENCH_SOURCE_BOUND_TIER"] = tier_name
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        isolated = tmp_path / name.lower()
        isolated.mkdir(mode=0o700)
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(isolated)
    completed = subprocess.run(
        [
            str(installed_artifact.python),
            "-I",
            str(PROJECT_ROOT / "scripts/fresh_source_bound.py"),
        ],
        cwd=installed_artifact.run_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=175 * 60,
    )
    assert completed.returncode == 0, completed.stdout
    assert "Bearer " not in completed.stdout
    projection = _assert_common_bundle(evidence_root, tier_name)
    _assert_science(evidence_root, tier_name, projection)
    assert stat.S_IMODE(evidence_root.stat().st_mode) & 0o077 == 0


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_fresh_1pga_installed_public_run_retains_auditable_bundle(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_fresh("fresh-1pga", installed_artifact, tmp_path)


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_fresh_2emo_installed_public_run_retains_auditable_bundle(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_fresh("fresh-2emo", installed_artifact, tmp_path)


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_fresh_5g53_installed_public_run_retains_auditable_bundle(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_fresh("fresh-5g53", installed_artifact, tmp_path)
