"""Deterministic identity-addressed whole-Prompt edits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast, TypedDict

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


class InsertionDeclaration(TypedDict, total=False):
    """One Plan-admitted masked-residue insertion."""

    after_residue_id: str
    before_residue_id: str
    inserted_residue_ids: Sequence[str]


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


def edit_protein_prompt_layout(
    prompt: ProteinPrompt,
    target_layout: ResidueLayout,
    edits: Sequence[ResidueEditDeclaration],
) -> tuple[ProteinPrompt, ResidueMap]:
    """Apply one complete identity-addressed layout edit to every Prompt field."""
    source_layout = cast(ResidueLayout, prompt.target_layout)
    residue_map = build_residue_map(source_layout, target_layout, edits)
    source_index = {
        residue_id: index
        for index, residue_id in enumerate(source_layout.residue_ids)
    }

    def mapped_track(track: ResidueTrack | None) -> ResidueTrack | None:
        if track is None:
            return None
        return ResidueTrack(
            [
                (
                    track.values[source_index[residue_id]]
                    if residue_id in source_index
                    else None
                )
                for residue_id in target_layout.residue_ids
            ],
            None,
        )

    remapped_annotations = _remap_annotations(
        FunctionAnnotations(
            [
                annotation
                for annotation in prompt.function_annotations.annotations
                if annotation.start_residue_id in target_layout.residue_ids
                and annotation.end_residue_id in target_layout.residue_ids
            ]
        ),
        tuple(target_layout.residue_ids),
    )
    return (
        ProteinPrompt(
            target_layout=target_layout,
            sequence_track=cast(
                ResidueTrack,
                mapped_track(prompt.sequence_track),
            ),
            structure_track=cast(
                ResidueTrack,
                mapped_track(prompt.structure_track),
            ),
            secondary_structure_track=mapped_track(
                prompt.secondary_structure_track
            ),
            sasa_track=mapped_track(prompt.sasa_track),
            function_annotations=remapped_annotations,
        ),
        residue_map,
    )


def edit_protein_prompt_layout_from_declarations(
    prompt: ProteinPrompt,
    insertions: Sequence[InsertionDeclaration],
    deleted_residue_ids: Sequence[str],
) -> tuple[ProteinPrompt, ResidueMap]:
    """Derive and apply one complete target layout from exact declarations."""
    source_layout = cast(ResidueLayout, prompt.target_layout)
    source_ids = tuple(source_layout.residue_ids)
    source_index = {
        residue_id: index for index, residue_id in enumerate(source_ids)
    }
    deleted = set(deleted_residue_ids)
    if deleted - set(source_ids):
        raise ValueError("deleted_residue_ids contains an unknown residue")
    boundaries: dict[int, tuple[str, ...]] = {}
    inserted_ids: set[str] = set()
    for index, insertion in enumerate(insertions):
        after = insertion.get("after_residue_id")
        before = insertion.get("before_residue_id")
        if after is None and before is None:
            raise ValueError(
                f"insertions[{index}] requires an exact source boundary"
            )
        if after is not None and after not in source_index:
            raise ValueError(
                f"insertions[{index}] after anchor is unknown"
            )
        if before is not None and before not in source_index:
            raise ValueError(
                f"insertions[{index}] before anchor is unknown"
            )
        if after is not None and before is not None:
            boundary = source_index[after] + 1
            if source_index[before] != boundary:
                raise ValueError(
                    f"insertions[{index}] anchors are not adjacent"
                )
            chain_id = residue_chain(after)
            if residue_chain(before) != chain_id:
                raise ValueError(
                    f"insertions[{index}] boundary crosses a chain"
                )
        elif after is not None:
            boundary = source_index[after] + 1
            chain_id = residue_chain(after)
        else:
            boundary = source_index[cast(str, before)]
            chain_id = residue_chain(cast(str, before))
        declared_ids = tuple(insertion["inserted_residue_ids"])
        if boundary in boundaries:
            raise ValueError("insertions repeat one source boundary")
        if (
            set(declared_ids) & set(source_ids)
            or set(declared_ids) & inserted_ids
            or len(set(declared_ids)) != len(declared_ids)
        ):
            raise ValueError("insertions contain duplicate residue identities")
        if any(residue_chain(residue_id) != chain_id for residue_id in declared_ids):
            raise ValueError("inserted residue crosses its boundary chain")
        boundaries[boundary] = declared_ids
        inserted_ids.update(declared_ids)

    target_ids: list[str] = []
    for position in range(len(source_ids) + 1):
        target_ids.extend(boundaries.get(position, ()))
        if position < len(source_ids) and source_ids[position] not in deleted:
            target_ids.append(source_ids[position])
    target_chains = tuple(dict.fromkeys(residue_chain(item) for item in target_ids))
    target_layout = ResidueLayout(
        chain_id=",".join(target_chains),
        length=len(target_ids),
        residue_ids=target_ids,
    )
    edits: list[ResidueEditDeclaration] = [
        {
            "operation": "insert",
            "chain_id": residue_chain(residue_id),
            "residue_id": residue_id,
        }
        for residue_id in target_ids
        if residue_id in inserted_ids
    ]
    edits.extend(
        {
            "operation": "delete",
            "chain_id": residue_chain(residue_id),
            "residue_id": residue_id,
        }
        for residue_id in source_ids
        if residue_id in deleted
    )
    return edit_protein_prompt_layout(prompt, target_layout, edits)


def merge_protein_prompt_source(
    target: ProteinPrompt,
    source: ProteinPrompt,
    correspondence: Sequence[Mapping[str, str]],
    track_decisions: Mapping[str, str],
) -> ProteinPrompt:
    """Merge one Prompt source through confirmed exact residue correspondence."""
    target_layout = cast(ResidueLayout, target.target_layout)
    source_layout = cast(ResidueLayout, source.target_layout)
    target_index = {
        residue_id: index
        for index, residue_id in enumerate(target_layout.residue_ids)
    }
    source_index = {
        residue_id: index
        for index, residue_id in enumerate(source_layout.residue_ids)
    }
    matched = tuple(
        (
            source_index[item["source_residue_id"]],
            target_index[item["target_residue_id"]],
        )
        for item in correspondence
        if item["disposition"] == "match"
    )
    source_to_target = {
        source_layout.residue_ids[source_position]: (
            target_layout.residue_ids[target_position]
        )
        for source_position, target_position in matched
    }

    def merged_track(
        target_track: ResidueTrack | None,
        source_track: ResidueTrack | None,
        decision: str,
    ) -> ResidueTrack | None:
        if decision == "preserve":
            return _copy_residue_track(target_track)
        if source_track is None:
            return None
        values: list[Any] = (
            [None] * target_layout.length
            if target_track is None
            else list(target_track.values)
        )
        for source_position, target_position in matched:
            values[target_position] = source_track.values[source_position]
        return ResidueTrack(values, None)

    if track_decisions["function_annotations"] == "preserve":
        annotations = FunctionAnnotations(
            list(target.function_annotations.annotations)
        )
    else:
        annotations = FunctionAnnotations(
            sorted(
                (
                    FunctionAnnotation(
                        label=annotation.label,
                        start=(
                            target_index[
                                source_to_target[
                                    annotation.start_residue_id
                                ]
                            ]
                            + 1
                        ),
                        end=(
                            target_index[
                                source_to_target[
                                    annotation.end_residue_id
                                ]
                            ]
                            + 1
                        ),
                        chain_id=residue_chain(
                            source_to_target[annotation.start_residue_id]
                        ),
                        start_residue_id=source_to_target[
                            annotation.start_residue_id
                        ],
                        end_residue_id=source_to_target[
                            annotation.end_residue_id
                        ],
                    )
                    for annotation in source.function_annotations.annotations
                ),
                key=lambda item: (
                    item.start,
                    item.end,
                    item.label,
                    item.chain_id,
                    item.start_residue_id,
                    item.end_residue_id,
                ),
            )
        )

    return ProteinPrompt(
        target_layout=target_layout,
        sequence_track=cast(
            ResidueTrack,
            merged_track(
                target.sequence_track,
                source.sequence_track,
                track_decisions["sequence"],
            ),
        ),
        structure_track=cast(
            ResidueTrack,
            merged_track(
                target.structure_track,
                source.structure_track,
                track_decisions["structure"],
            ),
        ),
        secondary_structure_track=merged_track(
            target.secondary_structure_track,
            source.secondary_structure_track,
            track_decisions["secondary_structure"],
        ),
        sasa_track=merged_track(
            target.sasa_track,
            source.sasa_track,
            track_decisions["sasa"],
        ),
        function_annotations=annotations,
    )


def _copy_residue_track(track: ResidueTrack | None) -> ResidueTrack | None:
    return None if track is None else ResidueTrack(list(track.values), None)
