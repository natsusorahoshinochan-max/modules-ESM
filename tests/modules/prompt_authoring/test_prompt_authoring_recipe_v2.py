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
    payload = b">not-a-chain\nACD\n"
    assert parse_fasta_records(payload) == ("ACD",)
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


def test_randomly_inserted_prompt_output_supports_followup_edit_delete_and_insert() -> None:
    """The module accepts generated residues as ordinary input identities (Q20).

    This checks a subsequent module operation, not the editor's in-place document
    rewrite or its save interaction; those belong to the application journey.
    """
    source = ProteinSequence("AC", ("A:1", "A:2"))
    generated = _apply(
        sequence_source=source,
        document={
            "chains": [{"chain_id": "A", "length": 2}],
            "random_operations": [{"kind": "insert", "seed": 17, "count": 1}],
        },
    )
    inserted = set(generated.layout.residue_ids) - set(source.residue_ids)
    assert len(inserted) == 1
    random_id = next(iter(inserted))
    edited = _apply(
        prompt_source=generated,
        document={"track_edits": [{
            "track": "sequence", "action": "replace", "residue_id": random_id, "value": "G",
        }]},
    )
    assert edited.sequence[edited.layout.residue_ids.index(random_id)] == "G"

    target = []
    for residue_id in edited.layout.residue_ids:
        target.append({"residue_id": residue_id, "origin": "source"})
        if residue_id == random_id:
            target.append({"residue_id": "A:manual-followup", "origin": "inserted"})
    extended = _apply(prompt_source=edited, document={"target_residues": target})
    assert extended.layout.residue_ids[extended.layout.residue_ids.index(random_id) + 1] == "A:manual-followup"
    deleted = _apply(
        prompt_source=extended,
        document={"target_residues": [
            {"residue_id": residue_id, "origin": "source"}
            for residue_id in extended.layout.residue_ids if residue_id != random_id
        ]},
    )
    assert random_id not in deleted.layout.residue_ids
    assert "A:manual-followup" in deleted.layout.residue_ids
    assert tuple(
        residue_id for residue_id in deleted.layout.residue_ids
        if residue_id in source.residue_ids
    ) == source.residue_ids
    assert tuple(
        deleted.sequence[index] for index, residue_id in enumerate(deleted.layout.residue_ids)
        if residue_id in source.residue_ids
    ) == ("A", "C")


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
        "track_adoptions": [{"track": "sequence", "source_residue_ids": ["S:1"], "mask_policy": "adopt"}],
        "adopt_annotations": [],
        "remove_annotations": [],
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
                        "track_adoptions": [{"track": "sasa", "source_residue_ids": ["S:1"], "mask_policy": "adopt"}],
                        "adopt_annotations": [],
                        "remove_annotations": [],
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
                        "track_adoptions": [],
                        "adopt_annotations": [{"label": "site", "start_residue_id": "S:1", "end_residue_id": "S:3"}],
                        "remove_annotations": [],
                    }
                ]
            },
        )


def test_rigid_transforms_compose_after_coordinate_edits_and_keep_unselected() -> None:
    from dataclasses import replace
    from datatypes.structure import NamedAtomCoordinates

    target = replace(
        _prompt(("A:1", "A:2"), "AC"),
        coordinates=(
            NamedAtomCoordinates.from_mapping({"CA": (0., 0., 0.), "N": (0., 1., 0.)}),
            NamedAtomCoordinates.from_mapping({"CA": (9., 9., 9.)}),
        ),
    )
    result = _apply(prompt_source=target, document={
        "track_edits": [{"track": "coordinates", "action": "replace", "residue_id": "A:1", "value": {"atom_coordinates": [{"atom_name": "CA", "coordinates": [1., 0., 0.]}, {"atom_name": "N", "coordinates": [1., 1., 0.]}]}}],
        "rigid_transforms": [
            {"rotation_matrix": [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], "origin": [0., 0., 0.], "translation": [2., 0., 0.], "residue_ids": ["A:1"]},
            {"rotation_matrix": [[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]], "origin": [0., 0., 0.], "translation": [0., 0., 1.], "residue_ids": ["A:1"]},
        ],
    })
    assert result.coordinates[0] == NamedAtomCoordinates.from_mapping({"CA": (0., 3., 1.), "N": (-1., 3., 1.)})
    assert result.coordinates[1] == target.coordinates[1]


@pytest.mark.parametrize("mask_policy,expected", [("preserve", ("G", "C", "T")), ("adopt", ("G", None, "T"))])
def test_merge_adopts_explicit_regions_masks_and_new_residues(mask_policy: str, expected: tuple) -> None:
    from dataclasses import replace

    target = _prompt(("A:1", "A:2"), "AC")
    source = replace(_prompt(("S:1", "S:2", "S:3"), "GAT"), sequence=("G", None, "T"))
    result = _apply(prompt_source=target, merge_sources=(source,), document={
        "source_merges": [{
            "source_index": 0,
            "correspondence": [
                {"disposition": "match", "source_residue_id": "S:1", "target_residue_id": "A:1"},
                {"disposition": "match", "source_residue_id": "S:2", "target_residue_id": "A:2"},
                {"disposition": "insert", "source_residue_id": "S:3", "target_residue_id": "A:extension"},
            ],
            "track_adoptions": [{"track": "sequence", "source_residue_ids": ["S:1", "S:2", "S:3"], "mask_policy": mask_policy}],
            "adopt_annotations": [], "remove_annotations": [],
        }],
    })
    assert result.layout.residue_ids == ("A:1", "A:2", "A:extension")
    assert result.sequence == expected
    assert result.coordinates == (None, None, None)
    assert result.sasa is None


def test_merge_insertion_requires_explicit_annotation_removal_without_truncation() -> None:
    target = _prompt(("A:1", "A:2"), "AC", annotations=(FunctionAnnotation("target", "A:1", "A:2"),))
    source = _prompt(("S:1",), "G")
    merge = {
        "source_index": 0,
        "correspondence": [
            {"disposition": "target_gap", "target_residue_id": "A:1"},
            {"disposition": "insert", "source_residue_id": "S:1", "target_residue_id": "A:new"},
            {"disposition": "target_gap", "target_residue_id": "A:2"},
        ],
        "track_adoptions": [], "adopt_annotations": [], "remove_annotations": [],
    }
    with pytest.raises(ValueError, match="split an inherited function"):
        _apply(prompt_source=target, merge_sources=(source,), document={"source_merges": [merge]})
    merge["remove_annotations"] = [{"label": "target", "start_residue_id": "A:1", "end_residue_id": "A:2"}]
    result = _apply(prompt_source=target, merge_sources=(source,), document={"source_merges": [merge]})
    assert result.function_annotations == ()
    assert result.layout.residue_ids == ("A:1", "A:new", "A:2")


def test_explicit_edits_apply_to_merge_results() -> None:
    target = _prompt(("A:1",), "A")
    source = _prompt(("S:1",), "G")
    result = _apply(prompt_source=target, merge_sources=(source,), document={
        "source_merges": [{"source_index": 0, "correspondence": [{"disposition": "match", "source_residue_id": "S:1", "target_residue_id": "A:1"}], "track_adoptions": [{"track": "sequence", "source_residue_ids": ["S:1"], "mask_policy": "adopt"}], "adopt_annotations": [], "remove_annotations": []}],
        "track_edits": [{"track": "sequence", "action": "replace", "residue_id": "A:1", "value": "T"}],
    })
    assert result.sequence == ("T",)


def test_preserving_source_masks_keeps_optional_target_track_absent() -> None:
    source = _prompt(("S:1",), "A", secondary_structure=(None,))
    target = _prompt(("A:1",), "A")
    result = _apply(prompt_source=target, merge_sources=(source,), document={"source_merges": [{
        "source_index": 0,
        "correspondence": [{"disposition": "match", "source_residue_id": "S:1", "target_residue_id": "A:1"}],
        "track_adoptions": [{"track": "secondary_structure", "source_residue_ids": ["S:1"], "mask_policy": "preserve"}],
        "adopt_annotations": [], "remove_annotations": [],
    }]})
    assert result.secondary_structure is None


@pytest.mark.parametrize("extend_target", [False, True])
def test_final_function_replacement_does_not_erase_premerge_annotation_facts(extend_target: bool) -> None:
    target = _prompt(("A:1", "A:2"), "AC", annotations=(FunctionAnnotation("old", "A:1", "A:2"),))
    source = _prompt(("S:1",), "G")
    result = _apply(prompt_source=target, merge_sources=(source,), document={
        "target_residues": [{"residue_id": "A:1", "origin": "source"}, {"residue_id": "A:2", "origin": "source"}] + ([{"residue_id": "A:end", "origin": "inserted"}] if extend_target else []),
        "source_merges": [{
            "source_index": 0,
            "correspondence": [{"disposition": "target_gap", "target_residue_id": "A:1"}, {"disposition": "insert", "source_residue_id": "S:1", "target_residue_id": "A:new"}, {"disposition": "target_gap", "target_residue_id": "A:2"}] + ([{"disposition": "target_gap", "target_residue_id": "A:end"}] if extend_target else []),
            "track_adoptions": [], "adopt_annotations": [],
            "remove_annotations": [{"label": "old", "start_residue_id": "A:1", "end_residue_id": "A:2"}],
        }],
        "function_annotations": [{"label": "new", "start_residue_id": "A:new", "end_residue_id": "A:2"}],
    })
    assert result.function_annotations == (FunctionAnnotation("new", "A:new", "A:2"),)


@pytest.mark.parametrize("initial_kind", ["prompt", "blank"])
def test_merge_can_replace_every_residue_of_an_initially_declared_chain(initial_kind: str) -> None:
    document = {
        "target_residues": [],
        "source_merges": [{"source_index": 0, "correspondence": [{"disposition": "source_gap", "source_residue_id": "S:1"}, {"disposition": "insert", "source_residue_id": "S:2", "target_residue_id": "A:new"}], "track_adoptions": [{"track": "sequence", "source_residue_ids": ["S:2"], "mask_policy": "preserve"}], "adopt_annotations": [], "remove_annotations": []}],
    }
    if initial_kind == "blank":
        document["chains"] = [{"chain_id": "A", "length": 1}]
    result = _apply(prompt_source=_prompt(("A:1",), "A") if initial_kind == "prompt" else None, merge_sources=(_prompt(("S:1", "S:2"), "GW"),), document=document)
    assert result.layout.residue_ids == ("A:new",)
    assert result.layout.chain_ids == ("A",)
    assert result.sequence == ("W",)


def test_declared_multichain_scope_survives_empty_layout_and_multiple_merges() -> None:
    result = _apply(prompt_source=_prompt(("A:1", "B:1"), "AC"), merge_sources=(_prompt(("S:1",), "G"), _prompt(("T:1",), "W")), document={
        "target_residues": [],
        "source_merges": [
            {"source_index": 0, "correspondence": [{"disposition": "insert", "source_residue_id": "S:1", "target_residue_id": "A:new"}], "track_adoptions": [{"track": "sequence", "source_residue_ids": ["S:1"], "mask_policy": "adopt"}], "adopt_annotations": [], "remove_annotations": []},
            {"source_index": 1, "correspondence": [{"disposition": "target_gap", "target_residue_id": "A:new"}, {"disposition": "insert", "source_residue_id": "T:1", "target_residue_id": "B:new"}], "track_adoptions": [{"track": "sequence", "source_residue_ids": ["T:1"], "mask_policy": "adopt"}], "adopt_annotations": [], "remove_annotations": []},
        ],
    })
    assert result.layout.residue_ids == ("A:new", "B:new")
    assert result.layout.chain_ids == ("A", "B")
    assert result.sequence == ("G", "W")


def test_merge_source_does_not_expand_declared_target_chain_scope() -> None:
    with pytest.raises(ValueError, match="outside declared chains"):
        _apply(prompt_source=_prompt(("A:1",), "A"), merge_sources=(_prompt(("S:1",), "G"),), document={
            "target_residues": [],
            "source_merges": [{"source_index": 0, "correspondence": [{"disposition": "insert", "source_residue_id": "S:1", "target_residue_id": "S:new"}], "track_adoptions": [{"track": "sequence", "source_residue_ids": ["S:1"], "mask_policy": "preserve"}], "adopt_annotations": [], "remove_annotations": []}],
        })


def test_random_insert_document_keeps_generated_identity_during_layout_edits() -> None:
    source = ProteinSequence("AC", ("A:1", "A:2"))
    operation = {"kind": "insert", "seed": 17, "count": 1}
    document = {"chains": [{"chain_id": "A", "length": 2}], "random_operations": [operation]}
    generated = _apply(sequence_source=source, document=document)
    random_id = next(residue_id for residue_id in generated.layout.residue_ids if residue_id not in source.residue_ids)
    targets = []
    for residue_id in generated.layout.residue_ids:
        targets.append({"residue_id": residue_id, "origin": "source"})
        if residue_id == random_id:
            targets.append({"residue_id": "A:manual", "origin": "inserted"})
    edited = _apply(sequence_source=source, document={
        **document,
        "random_operations": [{**operation, "target_residues": targets}],
        "track_edits": [{"residue_id": random_id, "track": "sequence", "action": "replace", "value": "G"}],
    })
    index = edited.layout.residue_ids.index(random_id)
    assert edited.sequence[index] == "G"
    assert edited.layout.residue_ids[index + 1] == "A:manual"
    deleted = _apply(sequence_source=source, document={
        **document,
        "random_operations": [{**operation, "target_residues": [row for row in targets if row["residue_id"] != random_id]}],
    })
    assert random_id not in deleted.layout.residue_ids
    assert "A:manual" in deleted.layout.residue_ids
    assert tuple(residue_id for residue_id in deleted.layout.residue_ids if residue_id != "A:manual") == source.residue_ids
