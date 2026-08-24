"""Regenerate the locked task-shaped Workflow stress documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.catalog.builder import build_frozen_catalog
from core.workflow.compiler import lock_workflow
from protein_workbench_public.workflow_codec import (
    decode_workflow_document,
    encode_workflow_document,
)
from tests.support.workflow_stress import stress_registrations


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "workflow_stress"
SELECTION_CAPABILITIES = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "v2_workflows"
    / "exact_multi_objective_selection.workflow.json"
)


def _multi_selection() -> dict[str, Any]:
    payload = json.loads(SELECTION_CAPABILITIES.read_text(encoding="utf-8"))
    payload["workflow_id"] = "stress-multi-selection"
    payload["contract_lock"] = []
    nodes = {node["node_id"]: node for node in payload["nodes"]}
    nodes["select-filter"]["node_parameters"]["threshold"] = 0.95
    for node_id in ("select-filter", "select-sort", "select-top_k"):
        nodes[node_id]["node_parameters"]["out_of_scope_policy"] = "ignore"
    nodes["select-top_k"]["node_parameters"]["k"] = 2
    return payload


def _prompt_conditioning() -> dict[str, Any]:
    return {
        "schema_version": "2.1.0",
        "workflow_id": "stress-prompt-conditioning",
        "nodes": [
            {
                "node_id": "prompt-values",
                "node_type_id": "contract_test.prompt_authoring_values",
                "node_type_version": "4.0.0",
                "binding_id": "contract_test.prompt_authoring_values.direct",
                "binding_version": "4.0.0",
                "node_parameters": {"fixture": "3gb1-intent"},
                "binding_parameters": {},
            },
            {
                "node_id": "add-function",
                "node_type_id": "prompt_authoring.add_function_annotation",
                "node_type_version": "3.0.0",
                "binding_id": "prompt_authoring.add_function_annotation.direct",
                "binding_version": "3.0.0",
                "node_parameters": {
                    "annotation": {
                        "label": "binding_site",
                        "chain_id": "A",
                        "start_residue_id": "A:10",
                        "end_residue_id": "A:12",
                    },
                    "overlap_policy": "reject",
                },
                "binding_parameters": {},
            },
            {
                "node_id": "assemble-prompt",
                "node_type_id": "prompt_authoring.assemble_protein_prompt",
                "node_type_version": "3.0.0",
                "binding_id": "prompt_authoring.assemble_protein_prompt.direct",
                "binding_version": "3.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "mask-sequence",
                "node_type_id": "prompt_authoring.random_mask",
                "node_type_version": "3.0.0",
                "binding_id": "prompt_authoring.random_mask.direct",
                "binding_version": "3.0.0",
                "node_parameters": {
                    "effective_seed": 1603,
                    "count": 3,
                    "track": "sequence",
                    "eligible_residue_ids": ["A:20", "A:21", "A:22"],
                },
                "binding_parameters": {},
            },
            {
                "node_id": "generate-paired",
                "node_type_id": "esm3.generate_paired",
                "node_type_version": "8.0.0",
                "binding_id": "esm3.generate_paired.biohub_medium",
                "binding_version": "8.0.0",
                "node_parameters": {"effective_seed": 1603, "num_samples": 1},
                "binding_parameters": {},
            },
            {
                "node_id": "generate-sequence",
                "node_type_id": "esm3.generate_sequence",
                "node_type_version": "8.0.0",
                "binding_id": "esm3.generate_sequence.biohub_medium",
                "binding_version": "8.0.0",
                "node_parameters": {"effective_seed": 1604, "num_samples": 1},
                "binding_parameters": {},
            },
        ],
        "edges": [
            {
                "source_node_id": "prompt-values",
                "source_port": "source_layout",
                "target_node_id": "add-function",
                "target_port": "layout",
            },
            {
                "source_node_id": "prompt-values",
                "source_port": "source_layout",
                "target_node_id": "assemble-prompt",
                "target_port": "layout",
            },
            {
                "source_node_id": "prompt-values",
                "source_port": "source_sequence_track",
                "target_node_id": "assemble-prompt",
                "target_port": "sequence_track",
            },
            {
                "source_node_id": "prompt-values",
                "source_port": "source_structure_track",
                "target_node_id": "assemble-prompt",
                "target_port": "structure_track",
            },
            {
                "source_node_id": "prompt-values",
                "source_port": "source_visibility_track",
                "target_node_id": "assemble-prompt",
                "target_port": "visibility_track",
            },
            {
                "source_node_id": "prompt-values",
                "source_port": "source_secondary_structure_track",
                "target_node_id": "assemble-prompt",
                "target_port": "secondary_structure_track",
            },
            {
                "source_node_id": "prompt-values",
                "source_port": "source_sasa_track",
                "target_node_id": "assemble-prompt",
                "target_port": "sasa_track",
            },
            {
                "source_node_id": "add-function",
                "source_port": "function_annotations",
                "target_node_id": "assemble-prompt",
                "target_port": "function_annotations",
            },
            {
                "source_node_id": "assemble-prompt",
                "source_port": "protein_prompt",
                "target_node_id": "mask-sequence",
                "target_port": "protein_prompt",
            },
            {
                "source_node_id": "mask-sequence",
                "source_port": "protein_prompt",
                "target_node_id": "generate-paired",
                "target_port": "protein_prompt",
            },
            {
                "source_node_id": "mask-sequence",
                "source_port": "protein_prompt",
                "target_node_id": "generate-sequence",
                "target_port": "protein_prompt",
            },
        ],
        "observation_selectors": [],
        "selection_objectives": [],
        "contract_lock": [],
    }


def _multi_parent_batch() -> dict[str, Any]:
    return {
        "schema_version": "2.1.0",
        "workflow_id": "stress-multi-parent-batch",
        "nodes": [
            {
                "node_id": "structure-parents",
                "node_type_id": "contract_test.workflow_stress_structure_source",
                "node_type_version": "1.0.0",
                "binding_id": "contract_test.workflow_stress_structure_source.direct",
                "binding_version": "1.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "resolve-parent-axes",
                "node_type_id": "structure_transform.resolve_candidate_residue_axes",
                "node_type_version": "6.0.0",
                "binding_id": "structure_transform.resolve_candidate_residue_axes.direct",
                "binding_version": "6.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "design-children",
                "node_type_id": "proteinmpnn.design",
                "node_type_version": "10.0.0",
                "binding_id": "proteinmpnn.design.local",
                "binding_version": "11.0.0",
                "node_parameters": {
                    "effective_seed": 2066001,
                    "num_sequences": 2,
                    "temperature": 0.1,
                    "backbone_noise": 0,
                },
                "binding_parameters": {},
            },
            {
                "node_id": "fold-children",
                "node_type_id": "folding.fold",
                "node_type_version": "8.0.0",
                "binding_id": "folding.fold.esmfold2_remote",
                "binding_version": "9.0.0",
                "node_parameters": {"effective_seed": 2066002, "num_samples": 2},
                "binding_parameters": {},
            },
            {
                "node_id": "materialize-confidence",
                "node_type_id": "structure_prediction.materialize_confidence",
                "node_type_version": "2.0.0",
                "binding_id": "structure_prediction.materialize_confidence.direct",
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
        ],
        "edges": [
            {
                "source_node_id": "structure-parents",
                "source_port": "structure_candidates",
                "target_node_id": "resolve-parent-axes",
                "target_port": "structure_candidates",
            },
            {
                "source_node_id": "structure-parents",
                "source_port": "structure_candidates",
                "target_node_id": "design-children",
                "target_port": "structure_candidates",
            },
            {
                "source_node_id": "resolve-parent-axes",
                "source_port": "residue_axes",
                "target_node_id": "design-children",
                "target_port": "structure_residue_axes",
            },
            {
                "source_node_id": "structure-parents",
                "source_port": "sequence",
                "target_node_id": "design-children",
                "target_port": "sequence",
            },
            {
                "source_node_id": "design-children",
                "source_port": "sequence_candidates",
                "target_node_id": "fold-children",
                "target_port": "sequence_candidates",
            },
            {
                "source_node_id": "fold-children",
                "source_port": "structure_candidates",
                "target_node_id": "materialize-confidence",
                "target_port": "structure_candidates",
            },
            {
                "source_node_id": "fold-children",
                "source_port": "confidence_facts",
                "target_node_id": "materialize-confidence",
                "target_port": "confidence_facts",
            },
        ],
        "observation_selectors": [],
        "selection_objectives": [],
        "contract_lock": [],
    }


def _provider_downstream_commit() -> dict[str, Any]:
    payload = _multi_parent_batch()
    payload["workflow_id"] = "stress-provider-downstream-commit"
    payload["nodes"] = [
        node
        for node in payload["nodes"]
        if node["node_id"]
        in {"structure-parents", "resolve-parent-axes", "design-children"}
    ]
    payload["nodes"].append({
        "node_id": "take-designs",
        "node_type_id": "collection_ops.take_candidates",
        "node_type_version": "4.0.0",
        "binding_id": "collection_ops.take_candidates.direct",
        "binding_version": "4.0.0",
        "node_parameters": {"k": 2},
        "binding_parameters": {},
    })
    retained_node_ids = {node["node_id"] for node in payload["nodes"]}
    payload["edges"] = [
        edge
        for edge in payload["edges"]
        if edge["source_node_id"] in retained_node_ids
        and edge["target_node_id"] in retained_node_ids
    ]
    payload["edges"].append({
        "source_node_id": "design-children",
        "source_port": "sequence_candidates",
        "target_node_id": "take-designs",
        "target_port": "candidates",
    })
    return payload


def main() -> None:
    catalog = build_frozen_catalog(stress_registrations())
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    payloads = {
        "multi_selection.workflow.json": _multi_selection(),
        "prompt_conditioning.workflow.json": _prompt_conditioning(),
        "multi_parent_batch.workflow.json": _multi_parent_batch(),
        "provider_downstream_commit.workflow.json": (
            _provider_downstream_commit()
        ),
    }
    for filename, payload in payloads.items():
        locked = lock_workflow(decode_workflow_document(payload), catalog)
        path = OUTPUT_ROOT / filename
        path.write_text(
            json.dumps(
                encode_workflow_document(locked),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
