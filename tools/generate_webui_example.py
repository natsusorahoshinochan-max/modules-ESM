"""Regenerate the immutable 3GB1 WebUI example through backend owners."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.catalog.builder import build_frozen_catalog
from core.project.manager import WEBUI_3GB1_PROJECT_ID
from core.workflow.compiler import CompilationRequest, compile
from core.workflow.document import workflow_document_from_canonical
from protein_workbench_public.bootstrap import module_registrations


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "v2" / "webui-3gb1.example.json"

_AUTHOR_NODE_ID = "prompt-composition-webui-3gb1.source.author"
# A:39 is unresolved in 3GB1.pdb and therefore absent from the resolved axis.
_INSERTED_RESIDUE_IDS = (
    "A:inserted.cef4eec4d2634a90e4b1e54d",
    "A:inserted.8f408adb9e8e5c030e42815f",
)


def _node(
    node_id: str,
    node_type_id: str,
    binding_id: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type_id": node_type_id,
        "binding_id": binding_id,
        "node_parameters": parameters or {},
        "binding_parameters": {},
    }


def _edge(source: str, source_port: str, target: str, target_port: str) -> dict[str, str]:
    return {
        "source_node_id": source,
        "source_port": source_port,
        "target_node_id": target,
        "target_port": target_port,
    }


def _objective(
    objective_id: str,
    *,
    candidates: str,
    scores: str,
    metric: str,
    method: str,
    source_partition: str,
    utility_transform: str,
    weight: float,
    context: dict[str, Any],
    score_port: str = "scores",
) -> dict[str, Any]:
    return {
        "objective_id": objective_id,
        "candidate_input": {"node_id": candidates, "output_port": "structure_candidates"},
        "score_collection_input": {"node_id": scores, "output_port": score_port},
        "source_partition": source_partition,
        "metric": {"contract_kind": "metric", "contract_id": metric},
        "method": {"contract_kind": "method", "contract_id": method},
        "context_selector": context,
        "utility_transform": {
            "contract_kind": "utility_transform",
            "contract_id": utility_transform,
        },
        "utility_parameters": {},
        "weight": weight,
        "match_cardinality": "exactly_one",
        "missing_policy": "error",
    }


def _author_document() -> dict[str, Any]:
    source_ids = [
        f"A:{residue_number}"
        for residue_number in range(1, 57)
        if residue_number != 39
    ]
    target_residues: list[dict[str, str]] = [
        {"residue_id": residue_id, "origin": "source"}
        for residue_id in source_ids[:38]
    ]
    target_residues.extend(
        {"residue_id": residue_id, "origin": "inserted"}
        for residue_id in _INSERTED_RESIDUE_IDS
    )
    target_residues.extend(
        {"residue_id": residue_id, "origin": "source"}
        for residue_id in source_ids[38:]
    )
    sequence_clears = [
        "A:37",
        "A:38",
        *_INSERTED_RESIDUE_IDS,
        "A:40",
        "A:41",
    ]
    coordinate_clears = ["A:37", "A:38", "A:40", "A:41"]
    return {
        "target_residues": target_residues,
        "track_edits": [
            {"track": "sequence", "action": "clear", "residue_id": residue_id}
            for residue_id in sequence_clears
        ]
        + [
            {"track": "coordinates", "action": "clear", "residue_id": residue_id}
            for residue_id in coordinate_clears
        ],
    }


def _ordinary_graph() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    nodes = [
        _node("generate-paired", "esm3.generate_paired", "esm3.generate_paired.biohub_medium", {"effective_seed": 1603, "num_samples": 7}),
        _node("confidence-generated", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct"),
        _node("rank-generated", "selection.weighted_rank", "selection.weighted_rank.direct", {"objective_ids": ["generated-plddt"], "tie_policy": "candidate_id_ascending"}),
        _node("take-top-four", "collection_ops.take_candidates", "collection_ops.take_candidates.direct", {"k": 4}),
        _node("relation-generated-structure-parent", "collection_ops.relate_by_parent", "collection_ops.relate_by_parent.direct"),
        _node("relation-generated-pairs", "collection_ops.invert_relation", "collection_ops.invert_relation.direct"),
        _node("select-paired-sequences", "collection_ops.select_related_subjects", "collection_ops.select_related_subjects.direct"),
        _node("fold-stage-one", "folding.fold", "folding.fold.esmfold2_remote", {"effective_seed": 1603, "num_samples": 1}),
        _node("confidence-stage-one", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct"),
        _node("relation-stage-one-fold-parent", "collection_ops.relate_by_parent", "collection_ops.relate_by_parent.direct"),
        _node("relation-stage-one", "collection_ops.compose_relations", "collection_ops.compose_relations.direct"),
        _node("axes-stage-one", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("axes-generated-top-four", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("align-stage-one", "structure_comparison.align_pairs", "structure_comparison.align_pairs.sequence_primary_affine"),
        _node("tm-stage-one", "structure_comparison.tm_score_from_alignments", "structure_comparison.tm_score_from_alignments.from_alignment_evidence"),
        _node("scores-stage-one", "collection_ops.merge_scores", "collection_ops.merge_scores.direct"),
        _node("rank-stage-one", "selection.weighted_rank", "selection.weighted_rank.direct", {"objective_ids": ["stage-one-plddt", "stage-one-parent-tm"], "tie_policy": "candidate_id_ascending"}),
        _node("take-top-two", "collection_ops.take_candidates", "collection_ops.take_candidates.direct", {"k": 2}),
        _node("axes-top-two", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("design-children", "proteinmpnn.design", "proteinmpnn.design.local", {"effective_seed": 1603, "num_sequences": 3}),
        _node("fold-final", "folding.fold", "folding.fold.esmfold2_remote", {"effective_seed": 1603, "num_samples": 1}),
        _node("confidence-final", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct"),
        _node("relation-final-fold-parent", "collection_ops.relate_by_parent", "collection_ops.relate_by_parent.direct"),
        _node("relation-design-parent", "collection_ops.relate_by_parent", "collection_ops.relate_by_parent.direct"),
        _node("relation-final", "collection_ops.compose_relations", "collection_ops.compose_relations.direct"),
        _node("axes-final", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("align-final", "structure_comparison.align_pairs", "structure_comparison.align_pairs.sequence_primary_affine"),
        _node("tm-final", "structure_comparison.tm_score_from_alignments", "structure_comparison.tm_score_from_alignments.from_alignment_evidence"),
        _node("scores-final", "collection_ops.merge_scores", "collection_ops.merge_scores.direct"),
        _node("rank-final", "selection.weighted_rank", "selection.weighted_rank.direct", {"objective_ids": ["final-plddt", "final-parent-tm"], "tie_policy": "candidate_id_ascending"}),
        _node("take-top-three", "collection_ops.take_candidates", "collection_ops.take_candidates.direct", {"k": 3}),
        _node("export-final", "protein_io.export_structure", "protein_io.export_structure.direct"),
    ]
    e = _edge
    edges = [
        e(_AUTHOR_NODE_ID, "protein_prompt", "generate-paired", "protein_prompt"),
        e("generate-paired", "structure_candidates", "confidence-generated", "structure_candidates"),
        e("generate-paired", "confidence_facts", "confidence-generated", "confidence_facts"),
        e("generate-paired", "structure_candidates", "rank-generated", "candidates"),
        e("confidence-generated", "observations", "rank-generated", "scores"),
        e("rank-generated", "candidates", "take-top-four", "candidates"),
        e("generate-paired", "structure_candidates", "relation-generated-structure-parent", "subjects"),
        e("generate-paired", "sequence_candidates", "relation-generated-structure-parent", "parents"),
        e("relation-generated-structure-parent", "relation", "relation-generated-pairs", "relation"),
        e("generate-paired", "sequence_candidates", "select-paired-sequences", "subjects"),
        e("take-top-four", "candidates", "select-paired-sequences", "selected_references"),
        e("relation-generated-pairs", "relation", "select-paired-sequences", "relation"),
        e("select-paired-sequences", "candidates", "fold-stage-one", "sequence_candidates"),
        e("fold-stage-one", "structure_candidates", "confidence-stage-one", "structure_candidates"),
        e("fold-stage-one", "confidence_facts", "confidence-stage-one", "confidence_facts"),
        e("fold-stage-one", "structure_candidates", "relation-stage-one-fold-parent", "subjects"),
        e("select-paired-sequences", "candidates", "relation-stage-one-fold-parent", "parents"),
        e("relation-stage-one-fold-parent", "relation", "relation-stage-one", "left_relation"),
        e("select-paired-sequences", "relation", "relation-stage-one", "right_relation"),
        e("fold-stage-one", "structure_candidates", "axes-stage-one", "structure_candidates"),
        e("take-top-four", "candidates", "axes-generated-top-four", "structure_candidates"),
        e("fold-stage-one", "structure_candidates", "align-stage-one", "subjects"),
        e("axes-stage-one", "residue_axes", "align-stage-one", "subject_residue_axes"),
        e("take-top-four", "candidates", "align-stage-one", "references"),
        e("axes-generated-top-four", "residue_axes", "align-stage-one", "reference_residue_axes"),
        e("relation-stage-one", "relation", "align-stage-one", "relation"),
        e("align-stage-one", "alignments", "tm-stage-one", "alignments"),
        e("fold-stage-one", "structure_candidates", "tm-stage-one", "subjects"),
        e("take-top-four", "candidates", "tm-stage-one", "references"),
        e("relation-stage-one", "relation", "tm-stage-one", "relation"),
        e("confidence-stage-one", "observations", "scores-stage-one", "scores_a"),
        e("tm-stage-one", "scores", "scores-stage-one", "scores_b"),
        e("fold-stage-one", "structure_candidates", "rank-stage-one", "candidates"),
        e("scores-stage-one", "scores", "rank-stage-one", "scores"),
        e("rank-stage-one", "candidates", "take-top-two", "candidates"),
        e("take-top-two", "candidates", "axes-top-two", "structure_candidates"),
        e("take-top-two", "candidates", "design-children", "structure_candidates"),
        e("axes-top-two", "residue_axes", "design-children", "structure_residue_axes"),
        e("design-children", "sequence_candidates", "fold-final", "sequence_candidates"),
        e("fold-final", "structure_candidates", "confidence-final", "structure_candidates"),
        e("fold-final", "confidence_facts", "confidence-final", "confidence_facts"),
        e("fold-final", "structure_candidates", "relation-final-fold-parent", "subjects"),
        e("design-children", "sequence_candidates", "relation-final-fold-parent", "parents"),
        e("design-children", "sequence_candidates", "relation-design-parent", "subjects"),
        e("take-top-two", "candidates", "relation-design-parent", "parents"),
        e("relation-final-fold-parent", "relation", "relation-final", "left_relation"),
        e("relation-design-parent", "relation", "relation-final", "right_relation"),
        e("fold-final", "structure_candidates", "axes-final", "structure_candidates"),
        e("fold-final", "structure_candidates", "align-final", "subjects"),
        e("axes-final", "residue_axes", "align-final", "subject_residue_axes"),
        e("take-top-two", "candidates", "align-final", "references"),
        e("axes-top-two", "residue_axes", "align-final", "reference_residue_axes"),
        e("relation-final", "relation", "align-final", "relation"),
        e("align-final", "alignments", "tm-final", "alignments"),
        e("fold-final", "structure_candidates", "tm-final", "subjects"),
        e("take-top-two", "candidates", "tm-final", "references"),
        e("relation-final", "relation", "tm-final", "relation"),
        e("confidence-final", "observations", "scores-final", "scores_a"),
        e("tm-final", "scores", "scores-final", "scores_b"),
        e("fold-final", "structure_candidates", "rank-final", "candidates"),
        e("scores-final", "scores", "rank-final", "scores"),
        e("rank-final", "candidates", "take-top-three", "candidates"),
        e("take-top-three", "candidates", "export-final", "structures"),
    ]
    return nodes, edges


def main() -> None:
    registrations = module_registrations()
    catalog = build_frozen_catalog(registrations)
    source_nodes = [
        _node(
            "prompt-composition-webui-3gb1.source.import_structure",
            "protein_io.import_structure",
            "protein_io.import_structure.direct",
            {"project_input_ref": "3GB1.pdb"},
        ),
        _node(
            "prompt-composition-webui-3gb1.source.select_chains",
            "structure_transform.select_chains",
            "structure_transform.select_chains.direct",
            {"chain_ids": ["A"]},
        ),
        _node(
            "prompt-composition-webui-3gb1.source.resolve_axis",
            "structure_transform.resolve_residue_axis",
            "structure_transform.resolve_residue_axis.direct",
        ),
        _node(
            _AUTHOR_NODE_ID,
            "prompt_authoring.author",
            "prompt_authoring.author.direct",
            {"document": _author_document()},
        ),
    ]
    source_edges = [
        _edge(
            "prompt-composition-webui-3gb1.source.import_structure",
            "structure",
            "prompt-composition-webui-3gb1.source.select_chains",
            "structure",
        ),
        _edge(
            "prompt-composition-webui-3gb1.source.select_chains",
            "structure",
            "prompt-composition-webui-3gb1.source.resolve_axis",
            "structure",
        ),
        _edge(
            "prompt-composition-webui-3gb1.source.resolve_axis",
            "residue_axis",
            _AUTHOR_NODE_ID,
            "structure_source",
        ),
    ]
    ordinary_nodes, ordinary_edges = _ordinary_graph()
    intrinsic = {"kind": "intrinsic"}
    pairwise = {
        "kind": "pairwise",
        "subject_role": "subject",
        "reference_role": "reference",
        "pairing_mode": "explicit_relation",
        "normalization": "reference-axis-residue-count",
    }
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": WEBUI_3GB1_PROJECT_ID,
        "nodes": [*source_nodes, *ordinary_nodes],
        "edges": [*source_edges, *ordinary_edges],
        "observation_selectors": [],
        "selection_objectives": [
            _objective("generated-plddt", candidates="generate-paired", scores="confidence-generated", metric="structure.plddt.mean_residue", method="esm3.generate_paired.esm3_medium_2024_08", source_partition="prediction_confidence", utility_transform="structure.plddt.mean_residue.esm3_medium_2024_08.percent_to_unit", weight=1.0, context=intrinsic, score_port="observations"),
            _objective("stage-one-plddt", candidates="fold-stage-one", scores="scores-stage-one", metric="structure.plddt.mean_residue", method="folding.fold.esmfold2_fast_biohub_2026_05", source_partition="prediction_confidence", utility_transform="structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit", weight=0.5, context=intrinsic),
            _objective("stage-one-parent-tm", candidates="fold-stage-one", scores="scores-stage-one", metric="structure_comparison.tm_score", method="structure_comparison.tm_score.reference_axis_normalized.method", source_partition="structure_comparison.tm_score.explicit_relation", utility_transform="structure_comparison.tm_score.explicit_relation.identity", weight=0.5, context=pairwise),
            _objective("final-plddt", candidates="fold-final", scores="scores-final", metric="structure.plddt.mean_residue", method="folding.fold.esmfold2_fast_biohub_2026_05", source_partition="prediction_confidence", utility_transform="structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit", weight=0.5, context=intrinsic),
            _objective("final-parent-tm", candidates="fold-final", scores="scores-final", metric="structure_comparison.tm_score", method="structure_comparison.tm_score.reference_axis_normalized.method", source_partition="structure_comparison.tm_score.explicit_relation", utility_transform="structure_comparison.tm_score.explicit_relation.identity", weight=0.5, context=pairwise),
        ],
    }
    admitted = workflow_document_from_canonical(workflow)
    compile(CompilationRequest(admitted), catalog)
    OUTPUT.write_text(
        json.dumps(
            {"workflow": admitted.canonical_projection()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
