"""Public v2 contracts for cohesive residue-layout and track authoring."""

from __future__ import annotations

from pathlib import Path

from core import (
    ModulePackageContractCase,
    ModulePackagePortCase,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    discover_module_packages,
    verify_module_package_contract,
)
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    ResidueMap,
    ResidueTrack,
)
from modules.prompt_authoring.domain import AlignedResidueTrack
from modules.prompt_authoring.package import MODULE_PACKAGE
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)
from tests.fixtures.prompt_authoring_v2 import (
    SOURCE_LAYOUT,
    TARGET_LAYOUT,
    VERSION,
    wire_value,
)


def test_prompt_authoring_is_one_package_with_seven_independent_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["prompt_authoring"]
    assert registration.package_module == "modules.prompt_authoring"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/add_function_annotation.yaml",
        "definitions/assemble_protein_prompt.yaml",
        "definitions/build_residue_layout.yaml",
        "definitions/edit_residue_layout.yaml",
        "definitions/map_residue_track.yaml",
        "definitions/override_residue_track.yaml",
        "definitions/update_prompt_sequence.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    assert {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "prompt_authoring" in catalog.owners[
            (kind, contract_id, version)
        ]
    } == {
        ("prompt_authoring.add_function_annotation", VERSION),
        ("prompt_authoring.assemble_protein_prompt", VERSION),
        ("prompt_authoring.build_residue_layout", VERSION),
        ("prompt_authoring.edit_residue_layout", VERSION),
        ("prompt_authoring.map_residue_track", VERSION),
        ("prompt_authoring.override_residue_track", VERSION),
        ("prompt_authoring.update_prompt_sequence", VERSION),
    }


_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.prompt_authoring_values",
    node_type_version=VERSION,
    binding_id="contract_test.prompt_authoring_values.direct",
    binding_version=VERSION,
    node_parameters={},
    binding_parameters={},
)
_RESIDUE_MAP = ResidueMap(
    source_layout=SOURCE_LAYOUT,
    target_layout=TARGET_LAYOUT,
    mappings=[
        (0, 0, "match"),
        (-1, 1, "insert"),
        (2, 2, "match"),
        (1, -1, "delete"),
    ],
)
_ANNOTATIONS = FunctionAnnotations([
    FunctionAnnotation(
        label="binding_site",
        start=1,
        end=2,
        chain_id="A",
        start_residue_id="A:1",
        end_residue_id="A:2",
        overlap_policy="reject",
    ),
])
_PROTEIN_PROMPT = ProteinPrompt(
    target_layout=SOURCE_LAYOUT,
    sequence_track=ResidueTrack(["A", "G", "S"], None),
    function_annotations=_ANNOTATIONS,
)
_TRACK_PORT_CASES = (
    ModulePackagePortCase(
        "prompt_authoring.track.sequence",
        VERSION,
        AlignedResidueTrack(SOURCE_LAYOUT, ("A", None, "S")),
        (
            AlignedResidueTrack(SOURCE_LAYOUT, ("A", "?", "S")),
            AlignedResidueTrack(TARGET_LAYOUT, ("A", None)),
        ),
    ),
    ModulePackagePortCase(
        "prompt_authoring.track.structure",
        VERSION,
        AlignedResidueTrack(
            SOURCE_LAYOUT,
            (
                {"CA": (1.0, 2.0, 3.0)},
                None,
                {"CA": (4.0, 5.0, 6.0)},
            ),
        ),
        (
            AlignedResidueTrack(
                SOURCE_LAYOUT,
                ({"bad atom": (1.0, 2.0, 3.0)}, None, None),
            ),
            AlignedResidueTrack(
                SOURCE_LAYOUT,
                ((1.0, 2.0, 3.0), None, None),
            ),
        ),
    ),
    ModulePackagePortCase(
        "prompt_authoring.track.visibility",
        VERSION,
        AlignedResidueTrack(SOURCE_LAYOUT, (True, None, False)),
        (AlignedResidueTrack(SOURCE_LAYOUT, (True, "visible", False)),),
    ),
    ModulePackagePortCase(
        "prompt_authoring.track.secondary_structure",
        VERSION,
        AlignedResidueTrack(SOURCE_LAYOUT, ("H", None, "-")),
        (AlignedResidueTrack(SOURCE_LAYOUT, ("helix", None, "-")),),
    ),
    ModulePackagePortCase(
        "prompt_authoring.track.sasa",
        VERSION,
        AlignedResidueTrack(SOURCE_LAYOUT, (0.0, None, 42.5)),
        (AlignedResidueTrack(SOURCE_LAYOUT, (0.0, None, -1.0)),),
    ),
    ModulePackagePortCase(
        "function.annotations",
        "2.1.0",
        _ANNOTATIONS,
        (
            FunctionAnnotations([
                FunctionAnnotation(
                    label="binding_site",
                    start=0,
                    end=2,
                    chain_id="A",
                    start_residue_id="A:1",
                    end_residue_id="A:2",
                    overlap_policy="reject",
                ),
            ]),
        ),
    ),
    ModulePackagePortCase(
        "protein.prompt",
        "2.1.0",
        _PROTEIN_PROMPT,
        (
            ProteinPrompt(
                target_layout=None,
                function_annotations=FunctionAnnotations(),
            ),
        ),
    ),
)


def test_all_seven_nodes_execute_through_shared_contract_kit(
    tmp_path: Path,
) -> None:
    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=(
            ModulePackageContractCase(
                case_id="prompt-authoring-add-function",
                node_type_id="prompt_authoring.add_function_annotation",
                node_type_version=VERSION,
                binding_id=(
                    "prompt_authoring.add_function_annotation.direct"
                ),
                binding_version=VERSION,
                node_parameters={
                    "annotation": {
                        "label": "active_site",
                        "chain_id": "A",
                        "start_residue_id": "A:1",
                        "end_residue_id": "A:2",
                    },
                    "overlap_policy": "reject",
                },
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-function-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "source_layout",
                        "contract-test-node",
                        "layout",
                    ),
                ),
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-assemble",
                node_type_id="prompt_authoring.assemble_protein_prompt",
                node_type_version=VERSION,
                binding_id=(
                    "prompt_authoring.assemble_protein_prompt.direct"
                ),
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-assemble-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "source_layout",
                        "contract-test-node",
                        "layout",
                    ),
                    WorkflowEdge(
                        "source",
                        "source_sequence_track",
                        "contract-test-node",
                        "sequence_track",
                    ),
                    WorkflowEdge(
                        "source",
                        "function_annotations",
                        "contract-test-node",
                        "function_annotations",
                    ),
                ),
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-build-layout",
                node_type_id="prompt_authoring.build_residue_layout",
                node_type_version=VERSION,
                binding_id="prompt_authoring.build_residue_layout.direct",
                binding_version=VERSION,
                node_parameters={
                    "chains": [
                        {"chain_id": "A", "length": 2},
                        {"chain_id": "B", "length": 1},
                    ],
                },
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-build-layout-v1",
                expected_scalar_outputs={
                    "layout": wire_value("residue.layout", SOURCE_LAYOUT),
                },
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-edit-layout",
                node_type_id="prompt_authoring.edit_residue_layout",
                node_type_version=VERSION,
                binding_id="prompt_authoring.edit_residue_layout.direct",
                binding_version=VERSION,
                node_parameters={
                    "edits": [
                        {
                            "operation": "delete",
                            "chain_id": "A",
                            "residue_id": "A:2",
                        },
                        {
                            "operation": "insert",
                            "chain_id": "A",
                            "residue_id": "A:new",
                        },
                    ]
                },
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-edit-layout-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "source_layout",
                        "contract-test-node",
                        "source_layout",
                    ),
                    WorkflowEdge(
                        "source",
                        "target_layout",
                        "contract-test-node",
                        "target_layout",
                    ),
                ),
                expected_scalar_outputs={
                    "residue_map": wire_value(
                        "residue.map",
                        _RESIDUE_MAP,
                    ),
                },
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-map-track",
                node_type_id="prompt_authoring.map_residue_track",
                node_type_version=VERSION,
                binding_id="prompt_authoring.map_residue_track.direct",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-map-track-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "source_sequence_track",
                        "contract-test-node",
                        "sequence_track",
                    ),
                    WorkflowEdge(
                        "source",
                        "residue_map",
                        "contract-test-node",
                        "residue_map",
                    ),
                ),
                expected_scalar_outputs={
                    "sequence_track": wire_value(
                        "prompt_authoring.track.sequence",
                        AlignedResidueTrack(
                            TARGET_LAYOUT,
                            ("A", None, "S"),
                        ),
                    ),
                },
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-override-track",
                node_type_id="prompt_authoring.override_residue_track",
                node_type_version=VERSION,
                binding_id="prompt_authoring.override_residue_track.direct",
                binding_version=VERSION,
                node_parameters={
                    "overrides": [
                        {
                            "action": "replace",
                            "residue_id": "A:1",
                            "value": "E",
                        },
                        {
                            "action": "clear",
                            "residue_id": "A:new",
                        },
                        {
                            "action": "preserve",
                            "residue_id": "B:1",
                        },
                    ]
                },
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-override-track-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "target_layout",
                        "contract-test-node",
                        "target_layout",
                    ),
                    WorkflowEdge(
                        "source",
                        "target_secondary_structure_track",
                        "contract-test-node",
                        "secondary_structure_track",
                    ),
                ),
                expected_scalar_outputs={
                    "secondary_structure_track": wire_value(
                        "prompt_authoring.track.secondary_structure",
                        AlignedResidueTrack(
                            TARGET_LAYOUT,
                            ("E", None, "-"),
                        ),
                    ),
                },
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-update-sequence",
                node_type_id="prompt_authoring.update_prompt_sequence",
                node_type_version=VERSION,
                binding_id=(
                    "prompt_authoring.update_prompt_sequence.direct"
                ),
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-update-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "protein_prompt",
                        "contract-test-node",
                        "protein_prompt",
                    ),
                    WorkflowEdge(
                        "source",
                        "protein_sequence",
                        "contract-test-node",
                        "sequence",
                    ),
                ),
            ),
        ),
        port_cases=_TRACK_PORT_CASES,
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert {
        identity
        for case in report.case_reports
        for identity in case.result_identities
    }
