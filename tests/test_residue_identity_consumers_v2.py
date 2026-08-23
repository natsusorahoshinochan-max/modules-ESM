"""Shared canonical ResidueIdentity grammar at consumer seams."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

import pytest

from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.parameters.contract import ParameterValueAdmissionError, admit_values
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotations,
    validate_canonical_function_annotations,
)
from datatypes.residue import ResidueLayout
from modules.proteinmpnn.domain import (
    ProteinMPNNConstraints,
    validate_proteinmpnn_constraints,
)
from modules.prompt_authoring.annotations import validate_function_annotations


def test_signed_residue_identities_address_constraints_and_annotations() -> None:
    layout = ResidueLayout(
        "A",
        4,
        ("A:-3", "A:-3A", "A:1", "A:2"),
    )
    constraints = ProteinMPNNConstraints(
        layout=layout,
        designable_residue_ids=("A:-3", "A:-3A", "A:1"),
        fixed_residue_ids=("A:2",),
        tied_residue_groups=(("A:-3", "A:-3A"),),
        bias_by_residue={"A:1": {"G": 0.5}},
    )
    annotations = FunctionAnnotations((
        FunctionAnnotation(
            label="signed_region",
            start=1,
            end=2,
            chain_id="A",
            start_residue_id="A:-3",
            end_residue_id="A:-3A",
            overlap_policy="reject",
        ),
    ))

    assert validate_function_annotations(annotations, layout) == annotations

    catalog = build_frozen_catalog(module_registrations())
    constraints_type = catalog.require_port_type(
        "proteinmpnn.constraints",
        "4.0.0",
    )
    annotations_type = catalog.require_port_type(
        "function.annotations",
        "3.0.0",
    )
    assert (
        constraints_type.decode(constraints_type.encode(constraints))
        == constraints
    )
    assert (
        annotations_type.decode(annotations_type.encode(annotations))
        == annotations
    )


def test_constraint_addresses_remain_closed_and_layout_bound() -> None:
    layout = ResidueLayout("A", 1, ("A:-3",))

    with pytest.raises(ValueError, match="'<chain>:<label>'"):
        validate_proteinmpnn_constraints(
            ProteinMPNNConstraints(
                layout=layout,
                fixed_residue_ids=("A:-1234",),
            )
        )
    with pytest.raises(ValueError, match="is not present in the layout"):
        validate_proteinmpnn_constraints(
            ProteinMPNNConstraints(
                layout=layout,
                fixed_residue_ids=("A:-4",),
            )
        )


def test_function_annotation_provenance_remains_closed_and_layout_bound() -> None:
    layout = ResidueLayout("A", 1, ("A:-3",))

    invalid = FunctionAnnotations((
        FunctionAnnotation(
            label="invalid",
            start=1,
            end=1,
            chain_id="A",
            start_residue_id="A:-1234",
            end_residue_id="A:-1234",
            overlap_policy="reject",
        ),
    ))
    with pytest.raises(ValueError, match="'<chain>:<label>'"):
        validate_canonical_function_annotations(invalid)

    absent = FunctionAnnotations((
        FunctionAnnotation(
            label="absent",
            start=1,
            end=1,
            chain_id="A",
            start_residue_id="A:-4",
            end_residue_id="A:-4",
            overlap_policy="reject",
        ),
    ))
    with pytest.raises(ValueError, match="do not correspond"):
        validate_function_annotations(absent, layout)


def test_signed_residue_identities_are_admitted_by_current_node_contracts() -> None:
    catalog = build_frozen_catalog(module_registrations())
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id="signed-residue-addresses",
        nodes=(
            WorkflowNodeInstance(
                node_id="constraints",
                node_type_id="proteinmpnn.constraints",
                node_type_version="4.0.0",
                binding_id="proteinmpnn.constraints.local",
                binding_version="4.0.0",
                node_parameters={
                    "designable_residue_ids": ["A:-3"],
                    "fixed_residue_ids": ["A:-3A"],
                    "tied_residue_groups": [["A:-3", "A:-3A"]],
                    "bias_by_residue": [
                        {
                            "residue_id": "A:-3",
                            "amino_acid": "G",
                            "bias": 0.5,
                        }
                    ],
                },
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="annotation",
                node_type_id="prompt_authoring.add_function_annotation",
                node_type_version="3.0.0",
                binding_id="prompt_authoring.add_function_annotation.direct",
                binding_version="3.0.0",
                node_parameters={
                    "annotation": {
                        "label": "signed_region",
                        "chain_id": "A",
                        "start_residue_id": "A:-3",
                        "end_residue_id": "A:-3A",
                    },
                    "overlap_policy": "reject",
                },
                binding_parameters={},
            ),
        ),
        edges=(),
        contract_lock=(),
    )

    admit_values(
        catalog.require_contract(
            "node_type",
            workflow.nodes[0].node_type_id,
            workflow.nodes[0].node_type_version,
        ).definition.parameter_contract,
        workflow.nodes[0].node_parameters,
    )
    admit_values(
        catalog.require_contract(
            "node_type",
            workflow.nodes[1].node_type_id,
            workflow.nodes[1].node_type_version,
        ).definition.parameter_contract,
        workflow.nodes[1].node_parameters,
    )

    invalid = WorkflowDocument(
        schema_version=workflow.schema_version,
        workflow_id=workflow.workflow_id,
        nodes=(
            WorkflowNodeInstance(
                node_id="annotation",
                node_type_id="prompt_authoring.add_function_annotation",
                node_type_version="3.0.0",
                binding_id="prompt_authoring.add_function_annotation.direct",
                binding_version="3.0.0",
                node_parameters={
                    "annotation": {
                        "label": "invalid",
                        "chain_id": "A",
                        "start_residue_id": "A:-1234",
                        "end_residue_id": "A:-1234",
                    },
                    "overlap_policy": "reject",
                },
                binding_parameters={},
            ),
        ),
        edges=(),
        contract_lock=(),
    )
    with pytest.raises(ParameterValueAdmissionError, match="must match"):
        admit_values(
            catalog.require_contract(
                "node_type",
                invalid.nodes[0].node_type_id,
                invalid.nodes[0].node_type_version,
            ).definition.parameter_contract,
            invalid.nodes[0].node_parameters,
        )
