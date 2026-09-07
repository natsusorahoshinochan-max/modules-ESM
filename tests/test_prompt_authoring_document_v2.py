"""Prompt Document admission agrees across Catalog and public protocol."""

from __future__ import annotations

import pytest

from core.catalog.builder import build_frozen_catalog
from core.parameters.contract import ParameterValueAdmissionError, admit_values
from core.parameters.model import ParameterContract
from protein_workbench_public.bootstrap import module_registrations
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    validate_schema,
)


@pytest.fixture(scope="module")
def authoring_parameter_contract() -> ParameterContract:
    catalog = build_frozen_catalog(module_registrations())
    return catalog.require_contract(
        "node_type",
        "prompt_authoring.author",
    ).definition.parameter_contract


def test_public_and_catalog_authoring_documents_share_nested_contracts(
    authoring_parameter_contract: ParameterContract,
) -> None:
    preserve_tracks = {
        track: "preserve"
        for track in (
            "sequence",
            "coordinates",
            "secondary_structure",
            "sasa",
            "function_annotations",
        )
    }
    valid = {
        "chains": [{"chain_id": "A", "length": 2}],
        "target_residues": [
            {"residue_id": "A:1", "origin": "source"},
            {"residue_id": "A:new", "origin": "inserted"},
        ],
        "track_edits": [
            {
                "track": "coordinates",
                "action": "replace",
                "residue_id": "A:1",
                "value": {
                    "atom_coordinates": [{"atom_name": "CA", "coordinates": [1, 2, 3]}]
                },
            }
        ],
        "rigid_transforms": [
            {
                "rotation_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "origin": [0, 0, 0],
                "translation": [1, 2, 3],
                "residue_ids": ["A:1"],
            }
        ],
        "function_annotations": [
            {
                "label": "site",
                "start_residue_id": "A:1",
                "end_residue_id": "A:new",
            }
        ],
        "random_operations": [
            {
                "kind": "mask",
                "seed": 1,
                "count": 1,
                "track": "sequence",
                "eligible_residue_ids": ["A:1"],
            },
            {
                "kind": "insert",
                "seed": 2,
                "count": 1,
                "eligible_chain_ids": ["A"],
            },
        ],
        "source_merges": [
            {
                "source_index": 0,
                "correspondence": [
                    {
                        "disposition": "match",
                        "source_residue_id": "S:1",
                        "target_residue_id": "A:1",
                    },
                    {
                        "disposition": "source_gap",
                        "source_residue_id": "S:2",
                    },
                    {
                        "disposition": "target_gap",
                        "target_residue_id": "A:new",
                    },
                ],
                "track_decisions": preserve_tracks,
            }
        ],
    }
    invalid = (
        {"chains": [{"chain_id": "header", "length": 1}]},
        {"target_residues": [{"residue_id": "", "origin": "source"}]},
        {
            "track_edits": [
                {
                    "track": "sequence",
                    "action": "replace",
                    "residue_id": "A:1",
                }
            ]
        },
        {
            "track_edits": [
                {
                    "track": "coordinates",
                    "action": "replace",
                    "residue_id": "A:1",
                    "value": {
                        "atom_coordinates": [{"atom_name": "CA", "coordinates": [1, 2]}]
                    },
                }
            ]
        },
        {
            "rigid_transforms": [
                {
                    "rotation_matrix": [[1, 0, 0], [0, 1, 0]],
                    "origin": [0, 0, 0],
                    "translation": [0, 0, 0],
                    "residue_ids": ["A:1"],
                }
            ]
        },
        {
            "function_annotations": [
                {
                    "label": "",
                    "start_residue_id": "A:1",
                    "end_residue_id": "A:1",
                }
            ]
        },
        {
            "random_operations": [
                {
                    "kind": "insert",
                    "seed": 1,
                    "count": 1,
                    "eligible_chain_ids": ["chain-A"],
                }
            ]
        },
        {
            "source_merges": [
                {
                    "source_index": 0,
                    "correspondence": [{"disposition": "match"}],
                    "track_decisions": preserve_tracks,
                }
            ]
        },
    )

    admit_values(authoring_parameter_contract, {"document": valid})
    validate_schema("#/$defs/PromptAuthoringDocument", valid)
    for document in invalid:
        with pytest.raises(ParameterValueAdmissionError):
            admit_values(authoring_parameter_contract, {"document": document})
        with pytest.raises(ProtocolValidationError):
            validate_schema("#/$defs/PromptAuthoringDocument", document)
