"""Public Workflow regressions for the workflow-usability repair contracts."""

from __future__ import annotations

from tests.support.ledger import public_run_projection

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
from datatypes.prompt import ProteinPrompt
from datatypes.residue import ResidueMap
from datatypes.structure import ProteinStructure
from modules.prompt_authoring.package import (
    MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
)
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from tests.fixtures.structure_transform_sources.package import (
    MODULE_PACKAGE as STRUCTURE_SOURCE_PACKAGE,
)


VERSION = "2.1.0"
STRUCTURE_VERSION = "4.0.0"
NORMALIZE_CSH_VERSION = "5.0.0"
SOURCE_VERSION = "6.0.0"
PROMPT_EDIT_VERSION = "3.0.0"
PROMPT_FROM_STRUCTURE_VERSION = "5.0.0"


def _run(
    tmp_path: Path,
    *,
    nodes: tuple[WorkflowNodeInstance, ...],
    edges: tuple[WorkflowEdge, ...],
    registrations: tuple[Any, ...],
) -> tuple[Any, V2RunService, dict[str, Any]]:
    catalog = build_frozen_catalog(registrations)
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("workflow usability repair regression")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version=VERSION,
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
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(catalog, {}),
            result_store(projects),
        ),
        result_store(projects),
    )
    receipt = service.start(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id="workflow-usability-repair",
    )
    projection = public_run_projection(service, project.id, receipt["run_id"])
    service.shutdown()
    return catalog, service, projection


def _decoded_outputs(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
) -> dict[tuple[str, str], object]:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    decoded: dict[tuple[str, str], object] = {}
    for output in projection["outputs"]:
        decoded[(output["node_id"], output["output_port"])] = (
            decode_service_typed_output_value(
                service,
                catalog,
                projection,
                output,
            )
        )
    return decoded


def test_2emo_csh_normalization_preserves_parent_span_and_builds_prompt(
    tmp_path: Path,
) -> None:
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_transform_source",
        node_type_version=SOURCE_VERSION,
        binding_id="contract_test.structure_transform_source.direct",
        binding_version=SOURCE_VERSION,
        node_parameters={"fixture": "2emo"},
        binding_parameters={},
    )
    normalize = WorkflowNodeInstance(
        node_id="normalize",
        node_type_id="structure_transform.normalize_csh_parent_span",
        node_type_version=NORMALIZE_CSH_VERSION,
        binding_id=(
            "structure_transform.normalize_csh_parent_span.direct"
        ),
        binding_version=NORMALIZE_CSH_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    prompt = WorkflowNodeInstance(
        node_id="prompt",
        node_type_id="prompt_authoring.prompt_from_structure",
        node_type_version=PROMPT_FROM_STRUCTURE_VERSION,
        binding_id="prompt_authoring.prompt_from_structure.direct",
        binding_version=PROMPT_FROM_STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    resolve_axis = WorkflowNodeInstance(
        node_id="resolve-axis",
        node_type_id="structure_transform.resolve_residue_axis",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.resolve_residue_axis.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    catalog, service, projection = _run(
        tmp_path,
        nodes=(source, normalize, resolve_axis, prompt),
        edges=(
            WorkflowEdge("source", "structure", "normalize", "structure"),
            WorkflowEdge(
                "normalize",
                "structure",
                "resolve-axis",
                "structure",
            ),
            WorkflowEdge(
                "normalize",
                "modified_residue_normalizations",
                "resolve-axis",
                "modified_residue_normalizations",
            ),
            WorkflowEdge(
                "resolve-axis",
                "residue_axis",
                "prompt",
                "residue_axis",
            ),
        ),
        registrations=(
            STRUCTURE_TRANSFORM_PACKAGE,
            PROMPT_AUTHORING_PACKAGE,
            STRUCTURE_SOURCE_PACKAGE,
        ),
    )

    assert projection["status"] == "succeeded"
    outputs = _decoded_outputs(catalog, service, projection)
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
    assert residue_ids[index : index + 5] == (
        "A:64",
        "A:65",
        "A:66",
        "A:67",
        "A:68",
    )
    assert prompt_value.sequence_track.values[index + 1 : index + 4] == (
        "S",
        "H",
        "G",
    )
    mapping = outputs[("normalize", "modified_residue_normalizations")]
    assert mapping.entries[0].component_id == "CSH"
    assert mapping.entries[0].observed_residue_id == "A:66"
    assert mapping.entries[0].parent_residue_ids == ("A:65", "A:66", "A:67")
    normalized_lines = normalized.pdb_string.splitlines()
    last_a64 = max(
        index
        for index, line in enumerate(normalized_lines)
        if line.startswith("ATOM  ")
        and line[21] == "A"
        and line[22:26].strip() == "64"
    )
    first_a65 = min(
        index
        for index, line in enumerate(normalized_lines)
        if line.startswith("ATOM  ")
        and line[21] == "A"
        and line[22:26].strip() == "65"
    )
    assert "TER" not in normalized_lines[last_a64 + 1 : first_a65]

    axis = outputs[("resolve-axis", "residue_axis")]
    assert axis.structure == normalized
    assert axis.layout.length == 224
    assert len(axis.segments) == 1
    assert axis.segments[0].chain_id == "A"
    assert axis.segments[0].residue_ids == axis.layout.residue_ids
    axis_index = axis.layout.residue_ids.index("A:64")
    assert axis.layout.residue_ids[axis_index : axis_index + 5] == (
        "A:64",
        "A:65",
        "A:66",
        "A:67",
        "A:68",
    )
    assert axis.sequence[axis_index + 1 : axis_index + 4] == "SHG"
    assert axis.ca_coordinate_mask[axis_index + 1] is True
    assert axis.complete_backbone_mask[axis_index + 1] is False
    assert axis.coordinate_for("A:65", "CA") == pytest.approx(
        (-12.147, 73.489, 39.240)
    )
    csh_disposition = next(
        item
        for item in axis.component_dispositions
        if item.component_id == "CSH"
    )
    assert csh_disposition.observed_residue_id == "A:66"
    assert csh_disposition.parent_residue_ids == ("A:65", "A:66", "A:67")
    assert csh_disposition.normalization_source == "explicit_mapping"


def test_2emo_raw_modified_polymer_is_rejected_at_residue_axis_seam(
    tmp_path: Path,
) -> None:
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_transform_source",
        node_type_version=SOURCE_VERSION,
        binding_id="contract_test.structure_transform_source.direct",
        binding_version=SOURCE_VERSION,
        node_parameters={"fixture": "2emo"},
        binding_parameters={},
    )
    resolve_axis = WorkflowNodeInstance(
        node_id="resolve-axis",
        node_type_id="structure_transform.resolve_residue_axis",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.resolve_residue_axis.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    _, _, projection = _run(
        tmp_path,
        nodes=(source, resolve_axis),
        edges=(
            WorkflowEdge(
                "source",
                "structure",
                "resolve-axis",
                "structure",
            ),
        ),
        registrations=(STRUCTURE_TRANSFORM_PACKAGE, STRUCTURE_SOURCE_PACKAGE),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "resolve-axis"
        for output in projection["outputs"]
    )


def test_5g53_identity_insertions_preserve_every_modeled_residue_and_track(
    tmp_path: Path,
) -> None:
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_transform_source",
        node_type_version=SOURCE_VERSION,
        binding_id="contract_test.structure_transform_source.direct",
        binding_version=SOURCE_VERSION,
        node_parameters={"fixture": "5g53"},
        binding_parameters={},
    )
    prompt = WorkflowNodeInstance(
        node_id="prompt",
        node_type_id="prompt_authoring.prompt_from_structure",
        node_type_version=PROMPT_FROM_STRUCTURE_VERSION,
        binding_id="prompt_authoring.prompt_from_structure.direct",
        binding_version=PROMPT_FROM_STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    select_chain_a = WorkflowNodeInstance(
        node_id="select-chain-a",
        node_type_id="structure_transform.select_chains",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.select_chains.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={"chain_ids": ["A"]},
        binding_parameters={},
    )
    resolve_axis = WorkflowNodeInstance(
        node_id="resolve-axis",
        node_type_id="structure_transform.resolve_residue_axis",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.resolve_residue_axis.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={},
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
            node_type_version=PROMPT_EDIT_VERSION,
            binding_id="prompt_authoring.insert_masked_residues.direct",
            binding_version=PROMPT_EDIT_VERSION,
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
    catalog, service, projection = _run(
        tmp_path,
        nodes=(source, select_chain_a, resolve_axis, prompt, *edit_nodes),
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
                "resolve-axis",
                "structure",
            ),
            WorkflowEdge(
                "resolve-axis",
                "residue_axis",
                "prompt",
                "residue_axis",
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
            STRUCTURE_SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
    )

    assert projection["status"] == "succeeded"
    outputs = _decoded_outputs(catalog, service, projection)
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
        assert tuple(
            residue_id
            for residue_id in target_ids
            if residue_id not in set(inserted_ids)
        ) == source_ids
        junction = target_ids.index("A:211")
        assert target_ids[
            junction + 1 : junction + 1 + len(inserted_ids)
        ] == tuple(inserted_ids)
        assert target_ids[junction + 1 + len(inserted_ids)] == "A:224"
        assert all(f"A:{index}" in target_ids for index in range(292, 313))
        assert sum(
            operation == "match"
            for _, _, operation in residue_map.mappings
        ) == 283
        assert sum(
            operation == "insert"
            for _, _, operation in residue_map.mappings
        ) == len(inserted_ids)
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
            retained = tuple(
                value
                for residue_id, value in zip(
                    target_ids,
                    edited_track.values,
                    strict=True,
                )
                if residue_id not in set(inserted_ids)
            )
            assert retained == source_track.values
            assert all(
                edited_track.values[target_ids.index(residue_id)] is None
                for residue_id in inserted_ids
            )
