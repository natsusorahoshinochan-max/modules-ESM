"""Public v2 contracts for cohesive residue-layout and track authoring."""

from __future__ import annotations

from protein_workbench_public.bootstrap import module_registrations

from pathlib import Path

import pytest

from core.catalog.builder import (
    build_frozen_catalog,
)
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackagePortCase,
    verify_module_package_contract,
)
from core.workflow.document import WorkflowNodeInstance
from core.workflow.document import WorkflowEdge
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
)
from modules.prompt_authoring.domain import AlignedResidueTrack
import modules.prompt_authoring.domain as prompt_domain
from modules.prompt_authoring.package import MODULE_PACKAGE
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)
from tests.fixtures.prompt_authoring_v2 import (
    SOURCE_LAYOUT,
    SOURCE_VERSION,
    TARGET_LAYOUT,
    VERSION,
    wire_value,
)


def test_prompt_residue_map_retains_its_supported_layout_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prompt_domain, "_MAX_RESIDUES", 1)
    layout = ResidueLayout("A", 2, ["A:1", "A:2"])
    residue_map = ResidueMap(
        layout,
        layout,
        [(0, 0, "match"), (1, 1, "match")],
    )

    with pytest.raises(ValueError, match="supported range"):
        prompt_domain.validate_residue_map(residue_map)


def test_prompt_authoring_is_one_package_with_twelve_independent_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in module_registrations()
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
        "definitions/insert_masked_residues.yaml",
        "definitions/map_residue_track.yaml",
        "definitions/override_residue_track.yaml",
        "definitions/override_protein_prompt_track.yaml",
        "definitions/prompt_from_structure.yaml",
        "definitions/random_insert_masked.yaml",
        "definitions/random_mask.yaml",
        "definitions/update_prompt_sequence.yaml",
    }

    catalog = build_frozen_catalog(module_registrations())
    assert {
        (contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
        and contract.contract_id.startswith("prompt_authoring.")
    } == {
        ("prompt_authoring.add_function_annotation", VERSION),
        ("prompt_authoring.assemble_protein_prompt", VERSION),
        ("prompt_authoring.build_residue_layout", VERSION),
        ("prompt_authoring.edit_residue_layout", VERSION),
        ("prompt_authoring.insert_masked_residues", VERSION),
        ("prompt_authoring.map_residue_track", VERSION),
        ("prompt_authoring.override_residue_track", VERSION),
        ("prompt_authoring.override_protein_prompt_track", VERSION),
        ("prompt_authoring.prompt_from_structure", "5.0.0"),
        ("prompt_authoring.random_insert_masked", VERSION),
        ("prompt_authoring.random_mask", VERSION),
        ("prompt_authoring.update_prompt_sequence", VERSION),
    }


def test_prompt_from_structure_uses_a_fresh_exact_method_identity() -> None:
    catalog = build_frozen_catalog(
        (MODULE_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    )

    method = catalog.require_contract(
        "method",
        "prompt_authoring.prompt_from_structure.method",
        "3.0.0",
    )
    assert method.descriptor["algorithm_identity"] == {
        "name": "canonical-resolved-axis-to-protein-prompt",
        "residue_identity": "resolved-axis-layout-order",
        "coordinates": "resolved-axis-selected-named-atoms",
        "visibility": "resolved-axis-coordinate-bearing-residues",
        "component_policy": "consume-resolver-admitted-polymer-axis",
    }

    binding = catalog.require_contract(
        "binding",
        "prompt_authoring.prompt_from_structure.direct",
        "5.0.0",
    )
    assert binding.descriptor["method"]["contract_version"] == "3.0.0"

    assert catalog.get_contract(
        "method",
        "prompt_authoring.prompt_from_structure.method",
        "2.1.0",
    ) is None
    assert catalog.get_contract(
        "node_type",
        "prompt_authoring.prompt_from_structure",
        "4.0.0",
    ) is None
    assert catalog.get_contract(
        "binding",
        "prompt_authoring.prompt_from_structure.direct",
        "4.0.0",
    ) is None


def test_prompt_sasa_nominal_ports_fix_absolute_square_angstrom_semantics() -> None:
    catalog = build_frozen_catalog((STRUCTURE_TRANSFORM_PACKAGE, MODULE_PACKAGE))
    quantity_contract = {
        "quantity": "solvent_accessible_surface_area",
        "measure": "absolute",
        "unit": "angstrom_squared",
        "granularity": "per_residue",
        "normalization": "none",
    }

    sasa_track = catalog.require_port_type(
        "prompt_authoring.track.sasa",
        VERSION,
    )
    assert sasa_track.validator.parameters["quantity_contract"] == (
        quantity_contract
    )

    protein_prompt = catalog.require_port_type("protein.prompt", VERSION)
    assert protein_prompt.validator.parameters["track_contracts"] == {
        "sasa_track": quantity_contract,
    }
    assemble = catalog.require_contract(
        "node_type",
        "prompt_authoring.assemble_protein_prompt",
        VERSION,
    )
    assemble_sasa_input = next(
        port
        for port in assemble.descriptor["inputs"]
        if port["name"] == "sasa_track"
    )
    assert assemble_sasa_input["port_type"] == sasa_track.reference()


_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.prompt_authoring_values",
    node_type_version=SOURCE_VERSION,
    binding_id="contract_test.prompt_authoring_values.direct",
    binding_version=SOURCE_VERSION,
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
        "3.0.0",
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
        VERSION,
        _PROTEIN_PROMPT,
        (
            ProteinPrompt(
                target_layout=None,
                function_annotations=FunctionAnnotations(),
            ),
        ),
    ),
)


def test_all_twelve_nodes_execute_through_shared_contract_kit(
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
            ModulePackageContractCase(
                case_id="prompt-authoring-random-mask",
                node_type_id="prompt_authoring.random_mask",
                node_type_version=VERSION,
                binding_id="prompt_authoring.random_mask.direct",
                binding_version=VERSION,
                node_parameters={
                    "effective_seed": 73,
                    "count": 1,
                    "track": "sequence",
                    "eligible_residue_ids": [],
                },
                binding_parameters={},
                environment_values={},
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "protein_prompt",
                        "contract-test-node",
                        "protein_prompt",
                    ),
                ),
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-prompt-from-structure",
                node_type_id="prompt_authoring.prompt_from_structure",
                node_type_version="5.0.0",
                binding_id=(
                    "prompt_authoring.prompt_from_structure.direct"
                ),
                binding_version="5.0.0",
                node_parameters={},
                binding_parameters={},
                environment_values={},
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "resolved_residue_axis",
                        "contract-test-node",
                        "residue_axis",
                    ),
                ),
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-override-protein-prompt",
                node_type_id=(
                    "prompt_authoring.override_protein_prompt_track"
                ),
                node_type_version=VERSION,
                binding_id=(
                    "prompt_authoring.override_protein_prompt_track.direct"
                ),
                binding_version=VERSION,
                node_parameters={
                    "track": "secondary_structure",
                    "overrides": [
                        {
                            "action": "replace",
                            "residue_id": "A:1",
                            "value": "E",
                        },
                    ],
                },
                binding_parameters={},
                environment_values={},
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "protein_prompt",
                        "contract-test-node",
                        "protein_prompt",
                    ),
                ),
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-random-insert",
                node_type_id="prompt_authoring.random_insert_masked",
                node_type_version=VERSION,
                binding_id=(
                    "prompt_authoring.random_insert_masked.direct"
                ),
                binding_version=VERSION,
                node_parameters={
                    "effective_seed": 73,
                    "count": 1,
                    "eligible_chain_ids": [],
                },
                binding_parameters={},
                environment_values={},
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "protein_prompt",
                        "contract-test-node",
                        "protein_prompt",
                    ),
                ),
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-deterministic-insert",
                node_type_id="prompt_authoring.insert_masked_residues",
                node_type_version=VERSION,
                binding_id=(
                    "prompt_authoring.insert_masked_residues.direct"
                ),
                binding_version=VERSION,
                node_parameters={
                    "insertions": [{
                        "after_residue_id": "A:1",
                        "before_residue_id": "A:2",
                        "inserted_residue_ids": ["A:inserted"],
                    }]
                },
                binding_parameters={},
                environment_values={},
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "protein_prompt",
                        "contract-test-node",
                        "protein_prompt",
                    ),
                ),
            ),
        ),
        port_cases=_TRACK_PORT_CASES,
        supporting_registrations=(SOURCE_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE),
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


def test_prompt_from_structure_consumes_only_the_resolved_residue_axis() -> None:
    catalog = build_frozen_catalog(
        (MODULE_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    )
    definition = catalog.require_contract(
        "node_type",
        "prompt_authoring.prompt_from_structure",
        "5.0.0",
    )

    inputs = definition.descriptor["inputs"]
    assert len(inputs) == 1
    assert inputs[0]["name"] == "residue_axis"
    assert {
        key: inputs[0]["port_type"][key]
        for key in ("contract_kind", "contract_id", "contract_version")
    } == {
        "contract_kind": "port_type",
        "contract_id": "structure_transform.resolved_residue_axis",
        "contract_version": "4.0.0",
    }
