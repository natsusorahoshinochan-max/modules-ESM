"""Deterministic identity-addressed whole-Prompt edits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypedDict

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

from .domain import (
    build_residue_map,
    ResidueEditDeclaration,
    residue_chain,
)


class InsertionDeclaration(TypedDict):
    """One Plan-admitted masked-residue insertion."""

    after_residue_id: str
    before_residue_id: str
    inserted_residue_ids: Sequence[str]


def _insertions_by_boundary(
    source_ids: tuple[str, ...],
    insertions: Sequence[InsertionDeclaration],
) -> dict[int, tuple[str, ...]]:
    source_index = {
        residue_id: index for index, residue_id in enumerate(source_ids)
    }
    source_set = set(source_ids)
    inserted_set: set[str] = set()
    boundaries: dict[int, tuple[str, ...]] = {}
    previous_boundary = -1
    for index, specification in enumerate(insertions):
        after = specification["after_residue_id"]
        before = specification["before_residue_id"]
        inserted = specification["inserted_residue_ids"]
        if after not in source_index or before not in source_index:
            raise ValueError(
                f"insertions[{index}] boundary contains an unknown residue"
            )
        after_index = source_index[after]
        if source_index[before] != after_index + 1:
            raise ValueError(
                f"insertions[{index}] anchors are not adjacent in source order"
            )
        chain = residue_chain(after)
        if residue_chain(before) != chain:
            raise ValueError(
                f"insertions[{index}] boundary crosses a chain"
            )
        if after_index <= previous_boundary:
            raise ValueError(
                "insertions must use unique boundaries in source order"
            )
        previous_boundary = after_index
        inserted_ids = tuple(inserted)
        if (
            len(set(inserted_ids)) != len(inserted_ids)
            or set(inserted_ids) & source_set
            or set(inserted_ids) & inserted_set
        ):
            raise ValueError(
                f"insertions[{index}] contains duplicate residue identities"
            )
        if any(residue_chain(residue_id) != chain for residue_id in inserted_ids):
            raise ValueError(
                f"insertions[{index}] residue identity crosses its boundary chain"
            )
        inserted_set.update(inserted_ids)
        boundaries[after_index] = inserted_ids
    return boundaries


def _extend_track(
    track: ResidueTrack | None,
    boundaries: Mapping[int, tuple[str, ...]],
) -> ResidueTrack | None:
    if track is None:
        return None
    values: list[object] = []
    for source_index, value in enumerate(track.values):
        values.append(value)
        values.extend(None for _ in boundaries.get(source_index, ()))
    return ResidueTrack(values, None)


def _remap_annotations(
    annotations: FunctionAnnotations,
    target_ids: tuple[str, ...],
) -> FunctionAnnotations:
    target_index = {
        residue_id: index for index, residue_id in enumerate(target_ids)
    }
    remapped = [
        FunctionAnnotation(
            label=annotation.label,
            start=target_index[annotation.start_residue_id] + 1,
            end=target_index[annotation.end_residue_id] + 1,
            chain_id=annotation.chain_id,
            start_residue_id=annotation.start_residue_id,
            end_residue_id=annotation.end_residue_id,
            overlap_policy=annotation.overlap_policy,
        )
        for annotation in annotations.annotations
    ]
    return FunctionAnnotations(sorted(
        remapped,
        key=lambda item: (
            item.start,
            item.end,
            item.label,
            item.chain_id,
            item.start_residue_id,
            item.end_residue_id,
        ),
    ))


def insert_masked_residues(
    prompt: ProteinPrompt,
    insertions: Sequence[InsertionDeclaration],
) -> tuple[ProteinPrompt, ResidueMap]:
    """Insert explicit identities at exact adjacent source boundaries."""
    source = prompt
    source_layout = source.target_layout
    assert source_layout is not None
    source_ids = tuple(source_layout.residue_ids or ())
    boundaries = _insertions_by_boundary(source_ids, insertions)
    inserted_count = sum(len(items) for items in boundaries.values())
    if source_layout.length + inserted_count > 2_000_000:
        raise ValueError("inserted layout exceeds the supported residue bound")

    target_ids: list[str] = []
    for source_index, residue_id in enumerate(source_ids):
        target_ids.append(residue_id)
        target_ids.extend(boundaries.get(source_index, ()))
    target_layout = ResidueLayout(
        chain_id=source_layout.chain_id,
        length=len(target_ids),
        residue_ids=target_ids,
    )
    edits: list[ResidueEditDeclaration] = [
        {
            "operation": "insert",
            "chain_id": residue_chain(residue_id),
            "residue_id": residue_id,
        }
        for inserted_ids in boundaries.values()
        for residue_id in inserted_ids
    ]
    residue_map = build_residue_map(source_layout, target_layout, edits)
    result = ProteinPrompt(
        target_layout=target_layout,
        sequence_track=_extend_track(source.sequence_track, boundaries),
        structure_track=_extend_track(source.structure_track, boundaries),
        structure_visibility_track=_extend_track(
            source.structure_visibility_track,
            boundaries,
        ),
        secondary_structure_track=_extend_track(
            source.secondary_structure_track,
            boundaries,
        ),
        sasa_track=_extend_track(source.sasa_track, boundaries),
        function_annotations=_remap_annotations(
            source.function_annotations,
            tuple(target_ids),
        ),
    )
    return result, residue_map
