"""Prompt recipe contracts for sources, identity, edits and correspondence."""

from __future__ import annotations

import pytest

from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotationTrack,
    ProteinPrompt,
)
from datatypes.residue import ResidueLayout
from datatypes.sequence import ProteinSequence
from modules.prompt_authoring.recipe import (
    apply_prompt_recipe,
)
from modules.protein_io.fasta import parse_fasta_records, parse_fasta_sequence


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


def test_merge_requires_complete_monotone_correspondence_and_keeps_target_gaps() -> (
    None
):
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
                        "track_decisions": _decisions(function_annotations="adopt"),
                    }
                ]
            },
        )
