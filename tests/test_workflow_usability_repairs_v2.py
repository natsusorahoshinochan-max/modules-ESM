"""Public Workflow regressions for the workflow-usability repair contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from datatypes import ProteinPrompt, ProteinStructure, ResidueMap
from modules.prompt_authoring.package import (
    MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
)
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as PROMPT_SOURCE_PACKAGE,
)


VERSION = "2.1.0"


def _run(
    tmp_path: Path,
    *,
    nodes: tuple[WorkflowNodeInstance, ...],
    edges: tuple[WorkflowEdge, ...],
    registrations: tuple[Any, ...],
) -> tuple[Any, dict[str, Any]]:
    catalog = build_frozen_catalog(registrations)
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("workflow usability repair regression")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version=VERSION,
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
        EnvironmentConfiguration({}),
    )
    receipt = service.start(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id="workflow-usability-repair",
    )
    projection = service.projection(project.id, receipt["run_id"])
    service.shutdown()
    return catalog, projection


def _decoded_outputs(
    catalog: Any,
    projection: dict[str, Any],
) -> dict[tuple[str, str], object]:
    decoded: dict[tuple[str, str], object] = {}
    for output in projection["outputs"]:
        reference = output["port_type"]
        port_type = catalog.require_port_type(
            reference["contract_id"],
            reference["contract_version"],
        )
        decoded[(output["node_id"], output["output_port"])] = (
            port_type.decode(
                canonical_json_bytes(
                    {
                        "schema_namespace": (
                            "protein-workbench-port-value/v2"
                        ),
                        "port_type_id": reference["contract_id"],
                        "port_type_version": reference[
                            "contract_version"
                        ],
                        "value": output["values"][0],
                    }
                )
            )
        )
    return decoded


def test_2emo_csh_normalization_preserves_parent_span_and_builds_prompt(
    tmp_path: Path,
) -> None:
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.prompt_authoring_values",
        node_type_version=VERSION,
        binding_id="contract_test.prompt_authoring_values.direct",
        binding_version=VERSION,
        node_parameters={"fixture": "2emo"},
        binding_parameters={},
    )
    normalize = WorkflowNodeInstance(
        node_id="normalize",
        node_type_id="structure_transform.normalize_csh_parent_span",
        node_type_version=VERSION,
        binding_id=(
            "structure_transform.normalize_csh_parent_span.direct"
        ),
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )
    prompt = WorkflowNodeInstance(
        node_id="prompt",
        node_type_id="prompt_authoring.prompt_from_structure",
        node_type_version=VERSION,
        binding_id="prompt_authoring.prompt_from_structure.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )
    catalog, projection = _run(
        tmp_path,
        nodes=(source, normalize, prompt),
        edges=(
            WorkflowEdge("source", "structure", "normalize", "structure"),
            WorkflowEdge("normalize", "structure", "prompt", "structure"),
        ),
        registrations=(
            STRUCTURE_TRANSFORM_PACKAGE,
            PROMPT_AUTHORING_PACKAGE,
            PROMPT_SOURCE_PACKAGE,
        ),
    )

    assert projection["status"] == "succeeded"
    outputs = _decoded_outputs(catalog, projection)
    normalized = outputs[("normalize", "structure")]
    prompt_value = outputs[("prompt", "protein_prompt")]
    assert type(normalized) is ProteinStructure
    assert type(prompt_value) is ProteinPrompt
    assert not any(
        line.startswith("HETATM") and line[17:20].strip() == "CSH"
        for line in normalized.pdb_string.splitlines()
    )
    residue_ids = prompt_value.target_layout.residue_ids
    assert prompt_value.target_layout.length == 224
    index = residue_ids.index("A:64")
    assert residue_ids[index : index + 5] == [
        "A:64",
        "A:65",
        "A:66",
        "A:67",
        "A:68",
    ]
    assert prompt_value.sequence_track.values[index + 1 : index + 4] == [
        "S",
        "H",
        "G",
    ]
    mapping = outputs[("normalize", "modified_residue_normalizations")]
    assert mapping.entries[0].component_id == "CSH"
    assert mapping.entries[0].observed_residue_id == "A:66"
    assert mapping.entries[0].parent_residue_ids == ("A:65", "A:66", "A:67")


def test_5g53_identity_insertions_preserve_every_modeled_residue_and_track(
    tmp_path: Path,
) -> None:
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.prompt_authoring_values",
        node_type_version=VERSION,
        binding_id="contract_test.prompt_authoring_values.direct",
        binding_version=VERSION,
        node_parameters={"fixture": "5g53"},
        binding_parameters={},
    )
    prompt = WorkflowNodeInstance(
        node_id="prompt",
        node_type_id="prompt_authoring.prompt_from_structure",
        node_type_version=VERSION,
        binding_id="prompt_authoring.prompt_from_structure.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )
    select_chain_a = WorkflowNodeInstance(
        node_id="select-chain-a",
        node_type_id="structure_transform.select_chains",
        node_type_version=VERSION,
        binding_id="structure_transform.select_chains.direct",
        binding_version=VERSION,
        node_parameters={"chain_ids": ["A"]},
        binding_parameters={},
    )
    branch_insertions = {
        "shorter": [
            f"A:gap211_224.short.{index:02d}" for index in range(1, 9)
        ],
        "numbering": [f"A:{index}" for index in range(212, 224)],
        "longer": [
            f"A:gap211_224.long.{index:02d}" for index in range(1, 17)
        ],
    }
    edit_nodes = tuple(
        WorkflowNodeInstance(
            node_id=f"edit-{branch}",
            node_type_id="prompt_authoring.insert_masked_residues",
            node_type_version=VERSION,
            binding_id="prompt_authoring.insert_masked_residues.direct",
            binding_version=VERSION,
            node_parameters={
                "insertions": [{
                    "after_residue_id": "A:211",
                    "before_residue_id": "A:224",
                    "inserted_residue_ids": inserted_ids,
                }]
            },
            binding_parameters={},
        )
        for branch, inserted_ids in branch_insertions.items()
    )
    catalog, projection = _run(
        tmp_path,
        nodes=(source, select_chain_a, prompt, *edit_nodes),
        edges=(
            WorkflowEdge(
                "source",
                "structure",
                "select-chain-a",
                "structure",
            ),
            WorkflowEdge(
                "select-chain-a",
                "structure",
                "prompt",
                "structure",
            ),
            *(
                WorkflowEdge(
                    "prompt",
                    "protein_prompt",
                    edit_node.node_id,
                    "protein_prompt",
                )
                for edit_node in edit_nodes
            ),
        ),
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROMPT_SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
    )

    assert projection["status"] == "succeeded"
    outputs = _decoded_outputs(catalog, projection)
    source_prompt = outputs[("prompt", "protein_prompt")]
    assert type(source_prompt) is ProteinPrompt
    source_ids = source_prompt.target_layout.residue_ids
    assert source_prompt.target_layout.length == 283
    assert source_ids[0] == "A:6"
    assert source_ids[-1] == "A:312"
    assert source_ids[source_ids.index("A:146") + 1] == "A:159"

    for branch, inserted_ids in branch_insertions.items():
        edited = outputs[(f"edit-{branch}", "protein_prompt")]
        residue_map = outputs[(f"edit-{branch}", "residue_map")]
        assert type(edited) is ProteinPrompt
        assert type(residue_map) is ResidueMap
        target_ids = edited.target_layout.residue_ids
        assert edited.target_layout.length == 283 + len(inserted_ids)
        assert target_ids[-1] == "A:312"
        assert [
            residue_id
            for residue_id in target_ids
            if residue_id not in set(inserted_ids)
        ] == source_ids
        junction = target_ids.index("A:211")
        assert target_ids[
            junction + 1 : junction + 1 + len(inserted_ids)
        ] == inserted_ids
        assert target_ids[junction + 1 + len(inserted_ids)] == "A:224"
        assert all(f"A:{index}" in target_ids for index in range(292, 313))
        assert sum(operation == "match" for _, _, operation in residue_map.mappings) == 283
        assert sum(operation == "insert" for _, _, operation in residue_map.mappings) == len(inserted_ids)
        assert all(operation != "delete" for _, _, operation in residue_map.mappings)
        for attribute in (
            "sequence_track",
            "structure_track",
            "structure_visibility_track",
            "secondary_structure_track",
            "sasa_track",
        ):
            source_track = getattr(source_prompt, attribute)
            edited_track = getattr(edited, attribute)
            if source_track is None:
                assert edited_track is None
                continue
            retained = [
                value
                for residue_id, value in zip(
                    target_ids,
                    edited_track.values,
                    strict=True,
                )
                if residue_id not in set(inserted_ids)
            ]
            assert retained == source_track.values
            assert all(
                edited_track.values[target_ids.index(residue_id)] is None
                for residue_id in inserted_ids
            )
