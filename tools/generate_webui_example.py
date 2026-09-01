"""Regenerate the immutable 3GB1 WebUI example through backend owners."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from core.catalog.authoring import build_authoring_capability_projection
from core.catalog.builder import build_frozen_catalog
from core.project.manager import ProjectManager, WEBUI_3GB1_PROJECT_ID
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.compiler import CompilationRequest, compile
from core.workflow.document import WorkflowDocument, workflow_document_from_canonical
from modules.prompt_authoring.authoring import PromptAuthoringService
from protein_workbench_public.bootstrap import module_registrations


ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = ROOT / "examples" / "v2" / "structures" / "3GB1.pdb"
OUTPUT = ROOT / "examples" / "v2" / "webui-3gb1.example.json"


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


def _prompt_draft(
    projects: ProjectManager,
    workflows: WorkflowAuthoringService,
) -> dict[str, Any]:
    project = projects.create("generator")
    projects.publish_input(
        project.id,
        "3GB1.pdb",
        STRUCTURE.read_bytes(),
        filename="3GB1.pdb",
    )
    workflows.save_draft(
        project.id,
        workflow=WorkflowDocument("2.1.0", project.id, (), ()),
    )
    prompts = PromptAuthoringService(projects, workflows)
    opened = prompts.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "pdb",
                "project_input_ref": "3GB1.pdb",
                "chain_ids": ["A"],
            },
        },
    )
    document = dict(opened.document)
    handles = {
        item["position"]: item["residue_handle"]
        for item in opened.residues
    }
    target = list(document["target_residues"])
    target[38:39] = [
        {"residue_handle": "inserted-loop-1", "origin": "insert", "chain_id": "A"},
        {"residue_handle": "inserted-loop-2", "origin": "insert", "chain_id": "A"},
    ]
    document["target_residues"] = target
    document["track_intents"] = [
        *(
            {
                "track": "sequence",
                "residue_handle": handle,
                "action": "mask",
            }
            for handle in (
                handles[37],
                handles[38],
                "inserted-loop-1",
                "inserted-loop-2",
                handles[40],
                handles[41],
            )
        ),
        *(
            {
                "track": "structure",
                "residue_handle": handles[position],
                "action": "mask",
            }
            for position in (37, 38, 40, 41)
        ),
    ]
    preview = prompts.preview(project.id, document)
    if preview.diagnostics:
        raise RuntimeError(tuple(item.projection() for item in preview.diagnostics))
    applied = prompts.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    old_id = applied.composition.composition_id
    projection = {
        "workflow": applied.draft.workflow.canonical_projection(),
        "authoring_compositions": [
            record.canonical_projection()
            for record in applied.draft.authoring_compositions
        ],
    }
    normalized = json.loads(
        json.dumps(projection).replace(old_id, "prompt-composition-webui-3gb1")
    )
    normalized["workflow"]["workflow_id"] = WEBUI_3GB1_PROJECT_ID
    return normalized


def _ordinary_graph(prompt_output: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    nodes = [
        _node("generate-paired", "esm3.generate_paired", "esm3.generate_paired.biohub_medium", {"effective_seed": 1603, "num_samples": 7}),
        _node("confidence-generated", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct"),
        _node("rank-generated", "selection.weighted_rank", "selection.weighted_rank.direct", {"objective_ids": ["generated-plddt"], "tie_policy": "candidate_id_ascending"}),
        _node("take-top-four", "collection_ops.take_candidates", "collection_ops.take_candidates.direct", {"k": 4}),
        _node("select-paired-sequences", "collection_ops.select_pairing_subjects", "collection_ops.select_pairing_subjects.direct"),
        _node("fold-stage-one", "folding.fold", "folding.fold.esmfold2_remote", {"effective_seed": 1603, "num_samples": 1}),
        _node("confidence-stage-one", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct"),
        _node("pair-stage-one", "collection_ops.rebind_candidate_pairing", "collection_ops.rebind_candidate_pairing.direct"),
        _node("axes-stage-one", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("axes-generated-top-four", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("align-stage-one", "structure_comparison.align_counterparts", "structure_comparison.align_counterparts.sequence_primary_affine"),
        _node("tm-stage-one", "structure_comparison.tm_score_counterparts", "structure_comparison.tm_score_counterparts.from_alignment_evidence"),
        _node("scores-stage-one", "collection_ops.merge_scores", "collection_ops.merge_scores.direct"),
        _node("rank-stage-one", "selection.weighted_rank", "selection.weighted_rank.direct", {"objective_ids": ["stage-one-plddt", "stage-one-parent-tm"], "tie_policy": "candidate_id_ascending"}),
        _node("take-top-two", "collection_ops.take_candidates", "collection_ops.take_candidates.direct", {"k": 2}),
        _node("axes-top-two", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("design-children", "proteinmpnn.design", "proteinmpnn.design.local", {"effective_seed": 1603, "num_sequences": 3}),
        _node("fold-final", "folding.fold", "folding.fold.esmfold2_remote", {"effective_seed": 1603, "num_samples": 1}),
        _node("confidence-final", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct"),
        _node("pair-final-ancestors", "collection_ops.pair_by_two_hop_ancestor", "collection_ops.pair_by_two_hop_ancestor.direct"),
        _node("axes-final", "structure_transform.resolve_candidate_residue_axes", "structure_transform.resolve_candidate_residue_axes.direct"),
        _node("align-final", "structure_comparison.align_direct_ancestors", "structure_comparison.align_direct_ancestors.sequence_primary_affine"),
        _node("tm-final", "structure_comparison.tm_score_direct_ancestors", "structure_comparison.tm_score_direct_ancestors.from_alignment_evidence"),
        _node("scores-final", "collection_ops.merge_scores", "collection_ops.merge_scores.direct"),
        _node("rank-final", "selection.weighted_rank", "selection.weighted_rank.direct", {"objective_ids": ["final-plddt", "final-parent-tm"], "tie_policy": "candidate_id_ascending"}),
        _node("take-top-three", "collection_ops.take_candidates", "collection_ops.take_candidates.direct", {"k": 3}),
        _node("export-final", "protein_io.export_structure", "protein_io.export_structure.direct"),
    ]
    e = _edge
    edges = [
        e(prompt_output["node_id"], prompt_output["port_name"], "generate-paired", "protein_prompt"),
        e("generate-paired", "structure_candidates", "confidence-generated", "structure_candidates"),
        e("generate-paired", "confidence_facts", "confidence-generated", "confidence_facts"),
        e("generate-paired", "structure_candidates", "rank-generated", "candidates"),
        e("confidence-generated", "observations", "rank-generated", "scores"),
        e("rank-generated", "candidates", "take-top-four", "candidates"),
        e("generate-paired", "sequence_candidates", "select-paired-sequences", "subjects"),
        e("take-top-four", "candidates", "select-paired-sequences", "selected_references"),
        e("generate-paired", "counterpart_pairs", "select-paired-sequences", "pairing"),
        e("select-paired-sequences", "candidates", "fold-stage-one", "sequence_candidates"),
        e("fold-stage-one", "structure_candidates", "confidence-stage-one", "structure_candidates"),
        e("fold-stage-one", "confidence_facts", "confidence-stage-one", "confidence_facts"),
        e("fold-stage-one", "structure_candidates", "pair-stage-one", "subjects"),
        e("select-paired-sequences", "candidates", "pair-stage-one", "parents"),
        e("take-top-four", "candidates", "pair-stage-one", "references"),
        e("select-paired-sequences", "pairing", "pair-stage-one", "parent_pairing"),
        e("fold-stage-one", "structure_candidates", "axes-stage-one", "structure_candidates"),
        e("take-top-four", "candidates", "axes-generated-top-four", "structure_candidates"),
        e("fold-stage-one", "structure_candidates", "align-stage-one", "subjects"),
        e("axes-stage-one", "residue_axes", "align-stage-one", "subject_residue_axes"),
        e("take-top-four", "candidates", "align-stage-one", "references"),
        e("axes-generated-top-four", "residue_axes", "align-stage-one", "reference_residue_axes"),
        e("pair-stage-one", "pairing", "align-stage-one", "pairing"),
        e("align-stage-one", "alignments", "tm-stage-one", "alignments"),
        e("fold-stage-one", "structure_candidates", "tm-stage-one", "subjects"),
        e("take-top-four", "candidates", "tm-stage-one", "references"),
        e("pair-stage-one", "pairing", "tm-stage-one", "pairing"),
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
        e("fold-final", "structure_candidates", "pair-final-ancestors", "subjects"),
        e("design-children", "sequence_candidates", "pair-final-ancestors", "intermediates"),
        e("take-top-two", "candidates", "pair-final-ancestors", "ancestors"),
        e("fold-final", "structure_candidates", "axes-final", "structure_candidates"),
        e("fold-final", "structure_candidates", "align-final", "subjects"),
        e("axes-final", "residue_axes", "align-final", "subject_residue_axes"),
        e("take-top-two", "candidates", "align-final", "references"),
        e("axes-top-two", "residue_axes", "align-final", "reference_residue_axes"),
        e("pair-final-ancestors", "pairing", "align-final", "pairing"),
        e("align-final", "alignments", "tm-final", "alignments"),
        e("fold-final", "structure_candidates", "tm-final", "subjects"),
        e("take-top-two", "candidates", "tm-final", "references"),
        e("pair-final-ancestors", "pairing", "tm-final", "pairing"),
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
    projection = build_authoring_capability_projection(registrations, catalog)
    with TemporaryDirectory() as directory:
        projects = ProjectManager(Path(directory) / "projects")
        workflows = WorkflowAuthoringService(projects, catalog, projection)
        example = _prompt_draft(projects, workflows)
    prompt_record = example["authoring_compositions"][0]
    prompt_output = next(
        item
        for item in prompt_record["exposed_outputs"]
        if item["role"] == "protein_prompt"
    )
    nodes, edges = _ordinary_graph(prompt_output)
    workflow = example["workflow"]
    workflow["nodes"].extend(nodes)
    workflow["edges"].extend(edges)
    intrinsic = {"kind": "intrinsic"}
    pairwise = {
        "kind": "pairwise",
        "subject_role": "subject",
        "reference_role": "reference",
        "pairing_mode": "per_subject_counterpart",
        "normalization": "reference-axis-residue-count",
    }
    direct = {**pairwise, "pairing_mode": "per_subject_direct_ancestor"}
    workflow["selection_objectives"] = [
        _objective("generated-plddt", candidates="generate-paired", scores="confidence-generated", metric="structure.plddt.mean_residue", method="esm3.generate_paired.esm3_medium_2024_08", source_partition="prediction_confidence", utility_transform="structure.plddt.mean_residue.esm3_medium_2024_08.percent_to_unit", weight=1.0, context=intrinsic, score_port="observations"),
        _objective("stage-one-plddt", candidates="fold-stage-one", scores="scores-stage-one", metric="structure.plddt.mean_residue", method="folding.fold.esmfold2_fast_biohub_2026_05", source_partition="prediction_confidence", utility_transform="structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit", weight=0.5, context=intrinsic),
        _objective("stage-one-parent-tm", candidates="fold-stage-one", scores="scores-stage-one", metric="structure_comparison.tm_score", method="structure_comparison.tm_score.reference_axis_normalized.method", source_partition="structure_comparison.tm_score.per_subject_counterpart", utility_transform="structure_comparison.tm_score.per_subject_counterpart.identity", weight=0.5, context=pairwise),
        _objective("final-plddt", candidates="fold-final", scores="scores-final", metric="structure.plddt.mean_residue", method="folding.fold.esmfold2_fast_biohub_2026_05", source_partition="prediction_confidence", utility_transform="structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit", weight=0.5, context=intrinsic),
        _objective("final-parent-tm", candidates="fold-final", scores="scores-final", metric="structure_comparison.tm_score", method="structure_comparison.tm_score.reference_axis_normalized.method", source_partition="structure_comparison.tm_score.per_subject_direct_ancestor", utility_transform="structure_comparison.tm_score.per_subject_direct_ancestor.identity", weight=0.5, context=direct),
    ]
    admitted = workflow_document_from_canonical(workflow)
    compile(CompilationRequest(admitted), catalog)
    OUTPUT.write_text(
        json.dumps(
            {
                "workflow": admitted.canonical_projection(),
                "authoring_compositions": example["authoring_compositions"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
