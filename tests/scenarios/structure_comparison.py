"""Shared structure comparison conformance scenarios and explicit expected values."""

from __future__ import annotations

from dataclasses import replace
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackagePortCase,
)
from core.workflow.document import WorkflowNodeInstance
from core.workflow.document import WorkflowEdge
from datatypes.candidate import CandidateDataReference
from modules.structure_comparison.contracts import (
    INSERTED_LOOP_EVALUATION_METHOD_REFERENCE,
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    SIMPLEFOLD_FOLD_METHOD_REFERENCE,
    THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from modules.structure_comparison.domain import (
    AtomPairDistanceEvidence,
    InsertedLoopCandidateEvidence,
    InsertedLoopEvaluationCollection,
    InsertedLoopThresholds,
    ResidueIdentityCorrespondence,
    ThreeWayComparisonEdge,
    ThreeWayConfidenceEvidence,
    ThreeWayConsistencyEvidence,
)


def _source_node(scenario: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_comparison_source",
        binding_id="contract_test.structure_comparison_source.fixture",
        node_parameters={"scenario": scenario},
        binding_parameters={},
    )


def _axis_node(node_id: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=node_id,
        node_type_id="structure_transform.resolve_candidate_residue_axes",
        binding_id="structure_transform.resolve_candidate_residue_axes.direct",
        node_parameters={},
        binding_parameters={},
    )


def _axis_edges() -> tuple[WorkflowEdge, ...]:
    return (
        WorkflowEdge(
            "source",
            "subjects",
            "subject-axis",
            "structure_candidates",
        ),
        WorkflowEdge(
            "source",
            "references",
            "reference-axis",
            "structure_candidates",
        ),
    )


def _alignment_edges(
    target_node_id: str,
    *,
    candidate_scope: bool,
) -> tuple[WorkflowEdge, ...]:
    """Wire one align_pairs or alignment-consuming metric node.

    `align_pairs` derives both scopes from its own ordered relation and axes,
    so only the alignment-consuming metric nodes still take complete Candidate
    scopes.
    """
    edges: list[WorkflowEdge] = []
    if candidate_scope:
        edges.append(
            WorkflowEdge("source", "subjects", target_node_id, "subjects")
        )
    edges.append(
        WorkflowEdge(
            "subject-axis",
            "residue_axes",
            target_node_id,
            "subject_residue_axes",
        )
    )
    if candidate_scope:
        edges.append(
            WorkflowEdge("source", "references", target_node_id, "references")
        )
    edges.append(
        WorkflowEdge(
            "reference-axis",
            "residue_axes",
            target_node_id,
            "reference_residue_axes",
        )
    )
    return tuple(edges)


def _ctk_case(
    *,
    case_id: str,
    operation: str,
    binding_id: str,
    pairing_mode: str | None,
) -> ModulePackageContractCase:
    assert pairing_mode == "explicit_relation"
    source = _source_node("explicit_relation")
    axis_nodes = (_axis_node("subject-axis"), _axis_node("reference-axis"))
    is_alignment = operation == "align_pairs"
    node_name = (
        "align_pairs"
        if is_alignment
        else f"{operation}_from_alignments"
    )
    if is_alignment:
        edges = (
            *_axis_edges(),
            *_alignment_edges("contract-test-node", candidate_scope=False),
            WorkflowEdge(
                "source", "pairing", "contract-test-node", "relation"
            ),
        )
        workflow_nodes = (source, *axis_nodes)
        node_parameters = {"pin_matching_chain_ids": False}
    else:
        alignment_binding = (
            "structure_comparison.align_pairs."
            "sequence_primary_affine"
        )
        alignment = WorkflowNodeInstance(
            node_id="alignment",
            node_type_id="structure_comparison.align_pairs",
            binding_id=alignment_binding,
            node_parameters={"pin_matching_chain_ids": False},
            binding_parameters={},
        )
        edges = (
            *_axis_edges(),
            *_alignment_edges("alignment", candidate_scope=False),
            WorkflowEdge(
                "alignment",
                "alignments",
                "contract-test-node",
                "alignments",
            ),
            WorkflowEdge(
                "source",
                "subjects",
                "contract-test-node",
                "subjects",
            ),
            WorkflowEdge(
                "source",
                "references",
                "contract-test-node",
                "references",
            ),
            WorkflowEdge(
                "source", "pairing", "alignment", "relation"
            ),
            WorkflowEdge(
                "source", "pairing", "contract-test-node", "relation"
            ),
        )
        workflow_nodes = (source, *axis_nodes, alignment)
        node_parameters = {}
    return ModulePackageContractCase(
        case_id=case_id,
        node_type_id=f"structure_comparison.{node_name}",
        binding_id=binding_id,
        node_parameters=node_parameters,
        binding_parameters={},
        environment_values={},
        workflow_nodes=workflow_nodes,
        workflow_edges=edges,
    )


def _three_way_node(
    node_id: str,
    node_type_id: str,
    binding_id: str,
) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=node_id,
        node_type_id=node_type_id,
        binding_id=binding_id,
        node_parameters=(
            {"pin_matching_chain_ids": False}
            if node_type_id.startswith("structure_comparison.align_")
            else {}
        ),
        binding_parameters={},
    )


def _inserted_loop_ctk_case(
    *,
    case_id: str = "evaluate-inserted-loop",
    missing_loop_plddt: bool = False,
    confidence_binding_id: str = (
        "contract_test.inserted_loop_confidence_source.fixture"
    ),
    confidence_fact_binding_id: str = (
        "contract_test.esmfold2_confidence_fact_source.fixture"
    ),
) -> ModulePackageContractCase:
    def operation_node(
        node_id: str,
        node_type_id: str,
        binding_id: str,
        parameters: dict[str, object] | None = None,
    ) -> WorkflowNodeInstance:
        return WorkflowNodeInstance(
            node_id=node_id,
            node_type_id=node_type_id,
            binding_id=binding_id,
            node_parameters=parameters or {},
            binding_parameters={},
        )

    source = operation_node(
        "loop-source",
        "contract_test.inserted_loop_source",
        "contract_test.inserted_loop_source.fixture",
    )
    subject_axis = operation_node(
        "loop-subject-axis",
        "structure_transform.resolve_candidate_residue_axes",
        "structure_transform.resolve_candidate_residue_axes.direct",
    )
    reference_axis = replace(subject_axis, node_id="loop-reference-axis")
    counterpart_axis = replace(subject_axis, node_id="loop-counterpart-axis")
    core_relation = operation_node(
        "loop-core-relation",
        "collection_ops.relate_to_single_reference",
        "collection_ops.relate_to_single_reference.direct",
    )
    core_alignment = operation_node(
        "loop-core-alignment",
        "structure_comparison.align_pairs",
        "structure_comparison.align_pairs.sequence_primary_affine",
        {"pin_matching_chain_ids": False},
    )
    core_tm = operation_node(
        "loop-core-tm",
        "structure_comparison.tm_score_from_alignments",
        "structure_comparison.tm_score_from_alignments.from_alignment_evidence",
    )
    core_rmsd = operation_node(
        "loop-core-rmsd",
        "structure_comparison.rmsd_from_alignments",
        "structure_comparison.rmsd_from_alignments.from_alignment_evidence",
    )
    counterpart_alignment = operation_node(
        "loop-counterpart-alignment",
        "structure_comparison.align_pairs",
        "structure_comparison.align_pairs.sequence_primary_affine",
        {"pin_matching_chain_ids": False},
    )
    counterpart_tm = operation_node(
        "loop-counterpart-tm",
        "structure_comparison.tm_score_from_alignments",
        "structure_comparison.tm_score_from_alignments.from_alignment_evidence",
    )
    counterpart_rmsd = operation_node(
        "loop-counterpart-rmsd",
        "structure_comparison.rmsd_from_alignments",
        "structure_comparison.rmsd_from_alignments.from_alignment_evidence",
    )
    prediction_axis = operation_node(
        "loop-prediction-axis",
        "contract_test.prediction_axis_source",
        "contract_test.prediction_axis_source.fixture",
    )
    confidence_facts = operation_node(
        "loop-confidence-facts",
        "contract_test.prediction_confidence_fact_source",
        confidence_fact_binding_id,
        {"missing_loop_plddt": missing_loop_plddt},
    )
    confidence = operation_node(
        "loop-confidence",
        "contract_test.prediction_confidence_source",
        confidence_binding_id,
    )
    edges = (
        WorkflowEdge("loop-source", "subjects", "loop-subject-axis", "structure_candidates"),
        WorkflowEdge("loop-source", "references", "loop-reference-axis", "structure_candidates"),
        WorkflowEdge("loop-source", "counterparts", "loop-counterpart-axis", "structure_candidates"),
        WorkflowEdge("loop-source", "subjects", "loop-core-relation", "subjects"),
        WorkflowEdge("loop-source", "references", "loop-core-relation", "references"),
        WorkflowEdge("loop-subject-axis", "residue_axes", "loop-core-alignment", "subject_residue_axes"),
        WorkflowEdge("loop-reference-axis", "residue_axes", "loop-core-alignment", "reference_residue_axes"),
        WorkflowEdge("loop-core-relation", "relation", "loop-core-alignment", "relation"),
        WorkflowEdge("loop-core-alignment", "alignments", "loop-core-tm", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-core-tm", "subjects"),
        WorkflowEdge("loop-source", "references", "loop-core-tm", "references"),
        WorkflowEdge("loop-core-relation", "relation", "loop-core-tm", "relation"),
        WorkflowEdge("loop-core-alignment", "alignments", "loop-core-rmsd", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-core-rmsd", "subjects"),
        WorkflowEdge("loop-source", "references", "loop-core-rmsd", "references"),
        WorkflowEdge("loop-core-relation", "relation", "loop-core-rmsd", "relation"),
        WorkflowEdge("loop-subject-axis", "residue_axes", "loop-counterpart-alignment", "subject_residue_axes"),
        WorkflowEdge("loop-counterpart-axis", "residue_axes", "loop-counterpart-alignment", "reference_residue_axes"),
        WorkflowEdge("loop-source", "pairing", "loop-counterpart-alignment", "relation"),
        WorkflowEdge("loop-counterpart-alignment", "alignments", "loop-counterpart-tm", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-counterpart-tm", "subjects"),
        WorkflowEdge("loop-source", "counterparts", "loop-counterpart-tm", "references"),
        WorkflowEdge("loop-source", "pairing", "loop-counterpart-tm", "relation"),
        WorkflowEdge("loop-counterpart-alignment", "alignments", "loop-counterpart-rmsd", "alignments"),
        WorkflowEdge("loop-source", "subjects", "loop-counterpart-rmsd", "subjects"),
        WorkflowEdge("loop-source", "counterparts", "loop-counterpart-rmsd", "references"),
        WorkflowEdge("loop-source", "pairing", "loop-counterpart-rmsd", "relation"),
        WorkflowEdge("loop-source", "sequence_parents", "loop-prediction-axis", "sequence_parents"),
        WorkflowEdge("loop-source", "subjects", "loop-confidence-facts", "structures"),
        WorkflowEdge("loop-prediction-axis", "prediction_axis", "loop-confidence-facts", "prediction_axis"),
        WorkflowEdge("loop-source", "subjects", "loop-confidence", "structures"),
        WorkflowEdge("loop-confidence-facts", "confidence_facts", "loop-confidence", "confidence_facts"),
        WorkflowEdge("loop-source", "subjects", "contract-test-node", "subjects"),
        WorkflowEdge("loop-subject-axis", "residue_axes", "contract-test-node", "subject_residue_axes"),
        WorkflowEdge("loop-source", "references", "contract-test-node", "references"),
        WorkflowEdge("loop-source", "counterparts", "contract-test-node", "counterparts"),
        WorkflowEdge("loop-source", "pairing", "contract-test-node", "counterpart_pairing"),
        WorkflowEdge("loop-core-alignment", "alignments", "contract-test-node", "resolved_core_alignments"),
        WorkflowEdge("loop-core-tm", "scores", "contract-test-node", "resolved_core_tm_scores"),
        WorkflowEdge("loop-core-rmsd", "scores", "contract-test-node", "resolved_core_rmsd_scores"),
        WorkflowEdge("loop-counterpart-alignment", "alignments", "contract-test-node", "counterpart_alignments"),
        WorkflowEdge("loop-counterpart-tm", "scores", "contract-test-node", "counterpart_tm_scores"),
        WorkflowEdge("loop-counterpart-rmsd", "scores", "contract-test-node", "counterpart_rmsd_scores"),
        WorkflowEdge("loop-confidence", "observations", "contract-test-node", "confidence_observations"),
    )
    return ModulePackageContractCase(
        case_id=case_id,
        node_type_id="structure_comparison.evaluate_inserted_loop",
        binding_id="structure_comparison.evaluate_inserted_loop.direct",
        node_parameters={
            "resolved_core_residue_ids": ["A:1", "A:2", "A:3", "A:4"],
            "loop_residue_ids": ["A:loop"],
            "left_junction_residue_id": "A:2",
            "right_junction_residue_id": "A:3",
            "resolved_core_tm_score_minimum": 0.75,
            "resolved_core_rmsd_angstrom_maximum": 3.0,
            "counterpart_tm_score_minimum": 0.70,
            "counterpart_rmsd_angstrom_maximum": 3.5,
            "resolved_core_mean_plddt_minimum": 70.0,
            "junction_cn_distance_angstrom_minimum": 1.15,
            "junction_cn_distance_angstrom_maximum": 1.55,
            "loop_core_nonbonded_distance_angstrom_minimum": 2.0,
        },
        binding_parameters={},
        environment_values={},
        workflow_nodes=(
            source,
            subject_axis,
            reference_axis,
            counterpart_axis,
            core_relation,
            core_alignment,
            core_tm,
            core_rmsd,
            counterpart_alignment,
            counterpart_tm,
            counterpart_rmsd,
            prediction_axis,
            confidence_facts,
            confidence,
        ),
        workflow_edges=edges,
    )


def _three_way_ctk_case(
    *,
    case_id: str = "classify-1pga-three-way-consistency",
    esmfold2_confidence_binding_id: str = (
        "contract_test.esmfold2_confidence_source.fixture"
    ),
    esmfold2_confidence_fact_binding_id: str = (
        "contract_test.esmfold2_confidence_fact_source.fixture"
    ),
) -> ModulePackageContractCase:
    source = _three_way_node(
        "source",
        "contract_test.1pga_three_way_source",
        "contract_test.1pga_three_way_source.fixture",
    )
    nodes = (
        source,
        *(
            _three_way_node(
                f"axis-{role}",
                "structure_transform.resolve_candidate_residue_axes",
                "structure_transform.resolve_candidate_residue_axes.direct",
            )
            for role in ("input", "esmfold2", "simplefold")
        ),
        _three_way_node(
            "relation-esmfold2-parent",
            "collection_ops.relate_by_parent",
            "collection_ops.relate_by_parent.direct",
        ),
        _three_way_node(
            "relation-simplefold-parent",
            "collection_ops.relate_by_parent",
            "collection_ops.relate_by_parent.direct",
        ),
        _three_way_node(
            "pair-methods",
            "collection_ops.join_relation_subjects",
            "collection_ops.join_relation_subjects.direct",
        ),
        _three_way_node(
            "relation-esmfold2-input",
            "collection_ops.relate_to_single_reference",
            "collection_ops.relate_to_single_reference.direct",
        ),
        _three_way_node(
            "relation-simplefold-input",
            "collection_ops.relate_to_single_reference",
            "collection_ops.relate_to_single_reference.direct",
        ),
        _three_way_node(
            "prediction-axis",
            "contract_test.prediction_axis_source",
            "contract_test.prediction_axis_source.fixture",
        ),
        _three_way_node(
            "align-esmfold2-input",
            "structure_comparison.align_pairs",
            "structure_comparison.align_pairs.sequence_primary_affine",
        ),
        _three_way_node(
            "align-simplefold-input",
            "structure_comparison.align_pairs",
            "structure_comparison.align_pairs.sequence_primary_affine",
        ),
        _three_way_node(
            "align-methods",
            "structure_comparison.align_pairs",
            "structure_comparison.align_pairs.sequence_primary_affine",
        ),
        *(
            _three_way_node(
                f"{metric}-{edge}",
                f"structure_comparison.{metric}_from_alignments",
                (
                    f"structure_comparison.{metric}_from_alignments."
                    "from_alignment_evidence"
                ),
            )
            for edge, mode in (
                ("esmfold2-input", "fixed_reference"),
                ("simplefold-input", "fixed_reference"),
                ("methods", "counterparts"),
            )
            for metric in ("tm_score", "rmsd")
        ),
        _three_way_node(
            "confidence-esmfold2",
            "contract_test.prediction_confidence_source",
            esmfold2_confidence_binding_id,
        ),
        _three_way_node(
            "confidence-fact-esmfold2",
            "contract_test.prediction_confidence_fact_source",
            esmfold2_confidence_fact_binding_id,
        ),
        _three_way_node(
            "confidence-simplefold",
            "contract_test.prediction_confidence_source",
            "contract_test.simplefold_confidence_source.fixture",
        ),
        _three_way_node(
            "confidence-fact-simplefold",
            "contract_test.prediction_confidence_fact_source",
            "contract_test.simplefold_confidence_fact_source.fixture",
        ),
    )
    edges: list[WorkflowEdge] = []
    for role, source_port in (
        ("input", "input_structures"),
        ("esmfold2", "esmfold2_structures"),
        ("simplefold", "simplefold_structures"),
    ):
        edges.append(
            WorkflowEdge(source.node_id, source_port, f"axis-{role}", "structure_candidates")
        )
    edges.extend(
        (
            WorkflowEdge("source", "esmfold2_structures", "relation-esmfold2-parent", "subjects"),
            WorkflowEdge("source", "sequence_parents", "relation-esmfold2-parent", "parents"),
            WorkflowEdge("source", "simplefold_structures", "relation-simplefold-parent", "subjects"),
            WorkflowEdge("source", "sequence_parents", "relation-simplefold-parent", "parents"),
            WorkflowEdge("relation-esmfold2-parent", "relation", "pair-methods", "left_relation"),
            WorkflowEdge("relation-simplefold-parent", "relation", "pair-methods", "right_relation"),
            WorkflowEdge("source", "esmfold2_structures", "relation-esmfold2-input", "subjects"),
            WorkflowEdge("source", "input_structures", "relation-esmfold2-input", "references"),
            WorkflowEdge("source", "simplefold_structures", "relation-simplefold-input", "subjects"),
            WorkflowEdge("source", "input_structures", "relation-simplefold-input", "references"),
            WorkflowEdge(
                "source",
                "sequence_parents",
                "prediction-axis",
                "sequence_parents",
            ),
        )
    )
    for edge_id, subject_role, reference_role, alignment_node in (
        ("esmfold2-input", "esmfold2", "input", "align-esmfold2-input"),
        ("simplefold-input", "simplefold", "input", "align-simplefold-input"),
        ("methods", "esmfold2", "simplefold", "align-methods"),
    ):
        edges.extend(
            (
                WorkflowEdge(f"axis-{subject_role}", "residue_axes", alignment_node, "subject_residue_axes"),
                WorkflowEdge(f"axis-{reference_role}", "residue_axes", alignment_node, "reference_residue_axes"),
            )
        )
        relation_node = (
            "pair-methods"
            if edge_id == "methods"
            else f"relation-{edge_id}"
        )
        edges.append(
            WorkflowEdge(relation_node, "relation", alignment_node, "relation")
        )
        for metric in ("tm_score", "rmsd"):
            score_node = f"{metric}-{edge_id}"
            edges.extend(
                (
                    WorkflowEdge(alignment_node, "alignments", score_node, "alignments"),
                    WorkflowEdge("source", f"{subject_role}_structures", score_node, "subjects"),
                    WorkflowEdge("source", f"{reference_role}_structures", score_node, "references"),
                )
            )
            edges.append(
                WorkflowEdge(relation_node, "relation", score_node, "relation")
            )
    for role in ("esmfold2", "simplefold"):
        edges.extend(
            (
                WorkflowEdge(
                    "prediction-axis",
                    "prediction_axis",
                    f"confidence-fact-{role}",
                    "prediction_axis",
                ),
                WorkflowEdge(
                    "source",
                    f"{role}_structures",
                    f"confidence-fact-{role}",
                    "structures",
                ),
                WorkflowEdge(
                    f"confidence-fact-{role}",
                    "confidence_facts",
                    f"confidence-{role}",
                    "confidence_facts",
                ),
                WorkflowEdge("source", f"{role}_structures", f"confidence-{role}", "structures"),
            )
        )
    target_ports = {
        "sequence_parents": ("source", "sequence_parents"),
        "esmfold2_structures": ("source", "esmfold2_structures"),
        "simplefold_structures": ("source", "simplefold_structures"),
        "input_residue_axes": ("axis-input", "residue_axes"),
        "esmfold2_residue_axes": ("axis-esmfold2", "residue_axes"),
        "simplefold_residue_axes": ("axis-simplefold", "residue_axes"),
        "method_pairing": ("pair-methods", "relation"),
        "input_esmfold2_alignments": ("align-esmfold2-input", "alignments"),
        "input_simplefold_alignments": ("align-simplefold-input", "alignments"),
        "method_alignments": ("align-methods", "alignments"),
        "input_esmfold2_tm_scores": ("tm_score-esmfold2-input", "scores"),
        "input_esmfold2_rmsd_scores": ("rmsd-esmfold2-input", "scores"),
        "input_simplefold_tm_scores": ("tm_score-simplefold-input", "scores"),
        "input_simplefold_rmsd_scores": ("rmsd-simplefold-input", "scores"),
        "method_tm_scores": ("tm_score-methods", "scores"),
        "method_rmsd_scores": ("rmsd-methods", "scores"),
        "esmfold2_confidence": ("confidence-esmfold2", "observations"),
        "simplefold_confidence": ("confidence-simplefold", "observations"),
    }
    edges.extend(
        WorkflowEdge(source_node, source_port, "contract-test-node", target_port)
        for target_port, (source_node, source_port) in target_ports.items()
    )
    return ModulePackageContractCase(
        case_id=case_id,
        node_type_id="structure_comparison.classify_three_way_consistency",
        binding_id="structure_comparison.classify_three_way_consistency.direct",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=nodes,
        workflow_edges=tuple(edges),
    )


def _three_way_consistency_value() -> ThreeWayConsistencyEvidence:
    input_reference = CandidateDataReference(
        "input", "protein.structure", "sha256:" + "5" * 64
    )
    sequence_reference = CandidateDataReference(
        "sequence", "protein.sequence", "sha256:" + "6" * 64
    )
    esmfold2_reference = CandidateDataReference(
        "esmfold2", "protein.structure", "sha256:" + "7" * 64
    )
    simplefold_reference = CandidateDataReference(
        "simplefold", "protein.structure", "sha256:" + "8" * 64
    )
    confidences = (
        ThreeWayConfidenceEvidence(
            "esmfold2",
            esmfold2_reference,
            REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
            90.0,
            True,
            "sha256:" + "9" * 64,
        ),
        ThreeWayConfidenceEvidence(
            "simplefold",
            simplefold_reference,
            SIMPLEFOLD_FOLD_METHOD_REFERENCE,
            90.0,
            True,
            "sha256:" + "a" * 64,
        ),
    )
    edge_specs = (
        ("input_esmfold2", esmfold2_reference, input_reference, "b", "c", "d"),
        ("input_simplefold", simplefold_reference, input_reference, "e", "f", "0"),
        (
            "esmfold2_simplefold",
            esmfold2_reference,
            simplefold_reference,
            "1",
            "2",
            "3",
        ),
    )
    edges = tuple(
        ThreeWayComparisonEdge(
            edge_id=edge_id,
            subject=subject,
            reference=reference_candidate,
            alignment_evidence_content_digest="sha256:" + digest * 64,
            alignment_method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
            normalization_length=75,
            aligned_atom_count=75,
            tm_score=1.0,
            rmsd_angstrom=0.0,
            tm_score_method=TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
            rmsd_method=RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
            tm_score_content_digest="sha256:" + tm_digest * 64,
            rmsd_content_digest="sha256:" + rmsd_digest * 64,
            close=True,
        )
        for edge_id, subject, reference_candidate, digest, tm_digest, rmsd_digest in edge_specs
    )
    return ThreeWayConsistencyEvidence(
        input_structure=input_reference,
        sequence_parent=sequence_reference,
        esmfold2_structure=esmfold2_reference,
        simplefold_structure=simplefold_reference,
        classification_method=THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
        input_b_factor_semantics="uninterpreted_coordinate_temperature_factor",
        residue_count=75,
        plddt_threshold=70.0,
        tm_score_threshold=0.8,
        rmsd_threshold_angstrom=2.5,
        confidences=confidences,
        edges=edges,
        classification="three_way_consistent",
        subreason=None,
    )


def _inserted_loop_port_case() -> ModulePackagePortCase:
    left_junction = AtomPairDistanceEvidence(
        "A:2",
        "A:2",
        "C",
        (0.0, 0.0, 0.0),
        "A:loop",
        "A:3",
        "N",
        (1.35, 0.0, 0.0),
        1.35,
    )
    right_junction = AtomPairDistanceEvidence(
        "A:loop",
        "A:3",
        "C",
        (0.0, 0.0, 0.0),
        "A:3",
        "A:4",
        "N",
        (1.35, 0.0, 0.0),
        1.35,
    )
    minimum_distance = AtomPairDistanceEvidence(
        "A:loop",
        "A:3",
        "CA",
        (0.0, 0.0, 0.0),
        "A:1",
        "A:1",
        "CA",
        (2.0, 0.0, 0.0),
        2.0,
    )
    loop_evidence = InsertedLoopEvaluationCollection(
        (
            InsertedLoopCandidateEvidence(
                subject=CandidateDataReference(
                    "loop-subject",
                    "protein.structure",
                    "sha256:" + "4" * 64,
                ),
                reference=CandidateDataReference(
                    "loop-reference",
                    "protein.structure",
                    "sha256:" + "5" * 64,
                ),
                counterpart=CandidateDataReference(
                    "loop-counterpart",
                    "protein.structure",
                    "sha256:" + "6" * 64,
                ),
                prediction_axis_content_digest="sha256:" + "7" * 64,
                structure_axis_content_digest="sha256:" + "8" * 64,
                prediction_to_structure_correspondence=(
                    ResidueIdentityCorrespondence("A:1", "A:1"),
                    ResidueIdentityCorrespondence("A:2", "A:2"),
                    ResidueIdentityCorrespondence("A:loop", "A:3"),
                    ResidueIdentityCorrespondence("A:3", "A:4"),
                    ResidueIdentityCorrespondence("A:4", "A:5"),
                ),
                resolved_core_residue_ids=("A:1", "A:2", "A:3", "A:4"),
                loop_residue_ids=("A:loop",),
                resolved_core_alignment_content_digest="sha256:" + "9" * 64,
                counterpart_alignment_content_digest="sha256:" + "a" * 64,
                resolved_core_tm_score=1.0,
                resolved_core_rmsd_angstrom=0.0,
                counterpart_tm_score=1.0,
                counterpart_rmsd_angstrom=0.0,
                confidence_collection_content_digest="sha256:" + "b" * 64,
                confidence_method=REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
                resolved_core_mean_plddt=90.0,
                loop_mean_plddt=80.0,
                left_junction=left_junction,
                right_junction=right_junction,
                minimum_loop_core_nonbonded_distance=minimum_distance,
                thresholds=InsertedLoopThresholds(
                    0.75, 3.0, 0.70, 3.5, 70.0, 1.15, 1.55, 2.0
                ),
                resolved_core_passed=True,
                counterpart_passed=True,
                confidence_passed=True,
                junctions_passed=True,
                clash_passed=True,
                accepted=True,
                method=INSERTED_LOOP_EVALUATION_METHOD_REFERENCE,
            ),
        )
    )
    return ModulePackagePortCase(
        "structure_comparison.inserted_loop_evaluation",
        loop_evidence,
        (
            object(),
            replace(
                loop_evidence,
                entries=(replace(loop_evidence.entries[0], accepted=False),),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        left_junction=replace(
                            left_junction,
                            left_structure_residue_id="A:4",
                        ),
                    ),
                ),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        left_junction=AtomPairDistanceEvidence(
                            "A:1",
                            "A:1",
                            "C",
                            (0.0, 0.0, 0.0),
                            "A:loop",
                            "A:3",
                            "N",
                            (1.35, 0.0, 0.0),
                            1.35,
                        ),
                    ),
                ),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        minimum_loop_core_nonbonded_distance=replace(
                            minimum_distance,
                            left_atom_name="H",
                            right_atom_name="H",
                        ),
                    ),
                ),
            ),
            replace(
                loop_evidence,
                entries=(
                    replace(
                        loop_evidence.entries[0],
                        confidence_method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
                    ),
                ),
            ),
        ),
    )
