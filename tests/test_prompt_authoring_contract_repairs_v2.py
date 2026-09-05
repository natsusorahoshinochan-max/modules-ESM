"""Focused regressions for the repaired Prompt Authoring contracts."""

from __future__ import annotations

import pytest

from core.catalog.builder import build_frozen_catalog
from core.parameters.contract import ParameterValueAdmissionError, admit_values
from core.parameters.model import ParameterContract
from datatypes.candidate import CandidateDataReference
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotationTrack,
    ProteinPrompt,
)
from datatypes.residue import CandidateResidueTrack, ResidueLayout, ResidueTrack
from datatypes.sequence import ProteinSequence
from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE
from modules.prompt_authoring.recipe import (
    _evaluate_prompt_recipe,
    apply_prompt_recipe,
)
from modules.protein_io.fasta import parse_fasta_records, parse_fasta_sequence
from modules.structure_annotation.port_types import _validate_observed_secondary
from protein_workbench_public.bootstrap import module_registrations
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    validate_schema,
)


def _prompt(
    residue_ids: tuple[str, ...],
    sequence: str,
    *,
    secondary_structure: tuple[str | None, ...] | None = None,
    sasa: tuple[float | None, ...] | None = None,
    annotations: tuple[FunctionAnnotation, ...] = (),
) -> ProteinPrompt:
    return ProteinPrompt(
        layout=ResidueLayout(residue_ids),
        sequence=tuple(sequence),
        coordinates=tuple(None for _ in residue_ids),
        secondary_structure=secondary_structure,
        sasa=sasa,
        function_annotations=annotations,
    )


def _apply(
    *,
    document: dict,
    sequence_source: ProteinSequence | None = None,
    prompt_source: ProteinPrompt | None = None,
    merge_sources: tuple[ProteinPrompt, ...] = (),
) -> ProteinPrompt:
    return apply_prompt_recipe(
        sequence_source=sequence_source,
        structure_source=None,
        prompt_source=prompt_source,
        merge_sources=merge_sources,
        document=document,
    )


def _decisions(**replacements: str) -> dict[str, str]:
    decisions = {
        "sequence": "preserve",
        "coordinates": "preserve",
        "secondary_structure": "preserve",
        "sasa": "preserve",
        "function_annotations": "preserve",
    }
    decisions.update(replacements)
    return decisions


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
                    "atom_coordinates": [
                        {"atom_name": "CA", "coordinates": [1, 2, 3]}
                    ]
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
                "track_decisions": _decisions(),
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
                        "atom_coordinates": [
                            {"atom_name": "CA", "coordinates": [1, 2]}
                        ]
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
                    "track_decisions": _decisions(),
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


def test_primary_source_is_optional_but_never_ambiguous() -> None:
    blank = _apply(document={"chains": [{"chain_id": "A", "length": 2}]})
    assert blank.layout.residue_ids == ("A:1", "A:2")

    with pytest.raises(ValueError, match="at most one primary source"):
        _apply(
            document={"chains": [{"chain_id": "A", "length": 2}]},
            sequence_source=ProteinSequence("AC"),
            prompt_source=_prompt(("A:1", "A:2"), "AC"),
        )


def test_sequence_source_uses_document_chains_without_fasta_header_identity() -> None:
    payload = b">not-a-chain\nAC\n>also-not-a-chain\nD\n"
    assert parse_fasta_records(payload) == ("AC", "D")
    assert parse_fasta_sequence(payload) == "ACD"

    prompt = _apply(
        document={
            "chains": [
                {"chain_id": "A", "length": 2},
                {"chain_id": "B", "length": 1},
            ]
        },
        sequence_source=ProteinSequence(parse_fasta_sequence(payload)),
    )
    assert prompt.layout.residue_ids == ("A:1", "A:2", "B:1")
    assert prompt.sequence == ("A", "C", "D")


def test_fasta_parser_leaves_empty_sequence_rejection_to_port_admission() -> None:
    assert parse_fasta_records(b">empty\n") == ("",)
    assert parse_fasta_sequence(b">empty\n") == ""


def test_sequence_source_preserves_existing_identity_and_checks_chain_layout() -> None:
    source = ProteinSequence(
        "ACD",
        residue_ids=("Q:10", "Q:10A", "R:-1"),
    )
    document = {
        "chains": [
            {"chain_id": "Q", "length": 2},
            {"chain_id": "R", "length": 1},
        ]
    }
    prompt = _apply(document=document, sequence_source=source)
    assert prompt.layout.residue_ids == source.residue_ids

    with pytest.raises(ValueError, match="do not match declared chains"):
        _apply(
            document={
                "chains": [
                    {"chain_id": "R", "length": 1},
                    {"chain_id": "Q", "length": 2},
                ]
            },
            sequence_source=source,
        )


def test_target_layout_can_delete_or_insert_but_cannot_reorder_source() -> None:
    source = _prompt(("A:1", "A:2", "A:3"), "ACD")
    with pytest.raises(ValueError, match="reorders source residue identities"):
        _apply(
            prompt_source=source,
            document={
                "target_residues": [
                    {"residue_id": "A:3", "origin": "source"},
                    {"residue_id": "A:2", "origin": "source"},
                    {"residue_id": "A:1", "origin": "source"},
                ]
            },
        )


def test_optional_track_clear_preserves_present_all_null_state() -> None:
    result = _apply(
        prompt_source=_prompt(("A:1", "A:2"), "AC"),
        document={
            "track_edits": [
                {
                    "track": "secondary_structure",
                    "action": "clear",
                    "residue_id": "A:1",
                }
            ]
        },
    )
    assert result.secondary_structure == (None, None)


def test_annotations_use_layout_order_and_explicit_empty_replaces() -> None:
    layout = ResidueLayout(("A:2", "A:10"))
    annotations = (
        FunctionAnnotation("first", "A:2", "A:2"),
        FunctionAnnotation("second", "A:10", "A:10"),
    )
    assert FunctionAnnotationTrack(layout, annotations).annotations == annotations

    inherited = _prompt(
        ("A:1", "A:2", "A:3"),
        "ACD",
        annotations=(FunctionAnnotation("site", "A:1", "A:3"),),
    )
    cleared = _apply(prompt_source=inherited, document={"function_annotations": []})
    assert cleared.function_annotations == ()

    with pytest.raises(ValueError, match="truncate an inherited"):
        _apply(
            prompt_source=inherited,
            document={
                "target_residues": [
                    {"residue_id": "A:1", "origin": "source"},
                    {"residue_id": "A:3", "origin": "source"},
                ]
            },
        )


def test_merge_requires_complete_monotone_correspondence_and_keeps_target_gaps() -> None:
    target = _prompt(("A:1", "A:2"), "AC")
    source = _prompt(("S:1", "S:2"), "GT")
    merge = {
        "source_index": 0,
        "correspondence": [
            {
                "disposition": "match",
                "source_residue_id": "S:1",
                "target_residue_id": "A:1",
            },
            {"disposition": "source_gap", "source_residue_id": "S:2"},
            {"disposition": "target_gap", "target_residue_id": "A:2"},
        ],
        "track_decisions": _decisions(sequence="adopt"),
    }
    merged = _apply(
        prompt_source=target,
        merge_sources=(source,),
        document={"source_merges": [merge]},
    )
    assert merged.sequence == ("G", "C")

    incomplete = {
        **merge,
        "correspondence": [
            {
                "disposition": "match",
                "source_residue_id": "S:1",
                "target_residue_id": "A:1",
            },
            {"disposition": "target_gap", "target_residue_id": "A:2"},
        ],
    }
    with pytest.raises(ValueError, match="cover source residues exactly once"):
        _apply(
            prompt_source=target,
            merge_sources=(source,),
            document={"source_merges": [incomplete]},
        )


def test_merge_rejects_absent_adopt_and_partial_annotation_mapping() -> None:
    target = _prompt(("A:1", "A:2"), "AC")
    source = _prompt(("S:1", "S:2"), "GT")
    complete = [
        {
            "disposition": "match",
            "source_residue_id": "S:1",
            "target_residue_id": "A:1",
        },
        {
            "disposition": "match",
            "source_residue_id": "S:2",
            "target_residue_id": "A:2",
        },
    ]
    with pytest.raises(ValueError, match="cannot adopt absent source track"):
        _apply(
            prompt_source=target,
            merge_sources=(source,),
            document={
                "source_merges": [
                    {
                        "source_index": 0,
                        "correspondence": complete,
                        "track_decisions": _decisions(sasa="adopt"),
                    }
                ]
            },
        )

    annotated_source = _prompt(
        ("S:1", "S:2", "S:3"),
        "GTA",
        annotations=(FunctionAnnotation("site", "S:1", "S:3"),),
    )
    target_three = _prompt(("A:1", "A:2", "A:3"), "ACD")
    with pytest.raises(ValueError, match="lose a function annotation interval"):
        _apply(
            prompt_source=target_three,
            merge_sources=(annotated_source,),
            document={
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
                                "target_residue_id": "A:2",
                            },
                            {
                                "disposition": "match",
                                "source_residue_id": "S:3",
                                "target_residue_id": "A:3",
                            },
                        ],
                        "track_decisions": _decisions(
                            function_annotations="adopt"
                        ),
                    }
                ]
            },
        )


def test_protein_prompt_codec_normalizes_only_sasa_json_integers() -> None:
    prompt = _prompt(("A:1", "A:2"), "AC", sasa=(0.0, 12.0))
    decoded = PROTEIN_PROMPT_PORT_TYPE.decode(
        PROTEIN_PROMPT_PORT_TYPE.encode(prompt)
    )
    assert decoded == prompt
    assert decoded.sasa is not None
    assert all(type(value) is float for value in decoded.sasa)


def test_random_insert_identity_and_trace_include_operation_index() -> None:
    prompt, trace = _evaluate_prompt_recipe(
        sequence_source=None,
        structure_source=None,
        prompt_source=None,
        merge_sources=(),
        document={
            "chains": [{"chain_id": "A", "length": 2}],
            "random_operations": [
                {"kind": "insert", "seed": 5, "count": 1},
                {"kind": "insert", "seed": 5, "count": 1},
            ],
        },
    )
    inserted = tuple(
        residue_id
        for residue_id in prompt.layout.residue_ids
        if ":masked." in residue_id
    )
    assert set(inserted) == {"A:masked.5.0.1", "A:masked.5.1.1"}
    assert tuple(item["operation_index"] for item in trace) == (0, 1)
    assert {item["residue_ids"][0] for item in trace} == set(inserted)


def test_observed_annotation_subject_must_reference_structure() -> None:
    observed = CandidateResidueTrack(
        subject=CandidateDataReference(
            candidate_id="sequence",
            data_type_id="protein.sequence",
            content_digest="sha256:" + "1" * 64,
        ),
        track=ResidueTrack(ResidueLayout(("A:1",)), ("H",)),
    )
    with pytest.raises(ValueError, match="protein.structure"):
        _validate_observed_secondary(observed)
