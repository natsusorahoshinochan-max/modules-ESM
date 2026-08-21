"""Seeded, provider-free stochastic ProteinPrompt authoring."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from core.operation import AdmittedPort
from core.port_types import canonical_json_bytes
from datatypes import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
)

from .domain import residue_chain


_TRACK_ATTRIBUTE = {
    "sequence": "sequence_track",
    "structure": "structure_track",
    "visibility": "structure_visibility_track",
    "secondary_structure": "secondary_structure_track",
    "sasa": "sasa_track",
}
_RANDOMNESS_NAMESPACE = "prompt-authoring-effective-randomness/v1"


def _random_digest(
    *,
    operation: str,
    effective_seed: int,
    draw: int,
    candidate: object,
) -> bytes:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "schema_namespace": _RANDOMNESS_NAMESPACE,
                "operation": operation,
                "effective_seed": effective_seed,
                "draw": draw,
                "candidate": candidate,
            }
        )
    ).digest()


def _copy_track(track: ResidueTrack | None) -> ResidueTrack | None:
    return (
        None
        if track is None
        else ResidueTrack(list(track.values), track.sentinel)
    )


def _copy_prompt(
    source: ProteinPrompt,
    *,
    tracks: Mapping[str, ResidueTrack | None] | None = None,
) -> ProteinPrompt:
    replacements = dict(tracks or {})
    return ProteinPrompt(
        target_layout=source.target_layout,
        sequence_track=replacements.get(
            "sequence_track",
            _copy_track(source.sequence_track),
        ),
        structure_track=replacements.get(
            "structure_track",
            _copy_track(source.structure_track),
        ),
        structure_visibility_track=replacements.get(
            "structure_visibility_track",
            _copy_track(source.structure_visibility_track),
        ),
        secondary_structure_track=replacements.get(
            "secondary_structure_track",
            _copy_track(source.secondary_structure_track),
        ),
        sasa_track=replacements.get(
            "sasa_track",
            _copy_track(source.sasa_track),
        ),
        function_annotations=FunctionAnnotations(
            list(source.function_annotations.annotations)
        ),
    )


def _resolved_mask_parameters(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    track: str,
    eligible_residue_ids: tuple[str, ...],
) -> tuple[
    ProteinPrompt,
    int,
    int,
    str,
    tuple[str, ...],
]:
    target_layout = prompt.target_layout
    assert target_layout is not None
    residue_ids = tuple(target_layout.residue_ids or ())
    residue_index = {
        residue_id: index for index, residue_id in enumerate(residue_ids)
    }
    if set(eligible_residue_ids) - set(residue_index):
        raise ValueError("eligible_residue_ids contains an unknown residue")
    attribute = _TRACK_ATTRIBUTE[track]
    selected_track = getattr(prompt, attribute)
    if selected_track is None:
        raise ValueError(f"protein_prompt has no {track} track to mask")
    allowed = eligible_residue_ids or residue_ids
    effective_eligibility = tuple(sorted(
        residue_id
        for residue_id in allowed
        if selected_track.values[residue_index[residue_id]] is not None
    ))
    if count > len(effective_eligibility):
        raise ValueError("count exceeds assigned eligible track positions")
    return (
        prompt,
        effective_seed,
        count,
        track,
        effective_eligibility,
    )


def resolve_random_mask_effective_randomness(
    *,
    inputs: Mapping[str, AdmittedPort],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the canonical effective random-mask set before Cache lookup."""
    source: ProteinPrompt = inputs["protein_prompt"].value
    seed = node_parameters["effective_seed"]
    count = node_parameters["count"]
    track = node_parameters["track"]
    declared_eligibility: tuple[str, ...] = node_parameters[
        "eligible_residue_ids"
    ]
    target_layout = source.target_layout
    assert target_layout is not None
    residue_ids = tuple(target_layout.residue_ids or ())
    residue_index = {
        residue_id: index for index, residue_id in enumerate(residue_ids)
    }
    selected_track = (
        getattr(source, _TRACK_ATTRIBUTE[track])
        if track in _TRACK_ATTRIBUTE
        else None
    )
    if (
        selected_track is None
        or set(declared_eligibility) - set(residue_index)
    ):
        eligibility = tuple(sorted(declared_eligibility))
    else:
        eligibility = tuple(sorted(
            residue_id
            for residue_id in (declared_eligibility or residue_ids)
            if selected_track.values[residue_index[residue_id]] is not None
        ))
    return {
        "effective_seed": seed,
        "count": count,
        "track": track,
        "eligible_residue_ids": list(eligibility),
    }


def random_mask_prompt(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    track: str,
    eligible_residue_ids: tuple[str, ...],
) -> ProteinPrompt:
    """Clear exactly ``count`` seeded assigned values on one declared track."""
    (
        source,
        effective_seed,
        count,
        track,
        effective_eligibility,
    ) = _resolved_mask_parameters(
        prompt,
        effective_seed=effective_seed,
        count=count,
        track=track,
        eligible_residue_ids=eligible_residue_ids,
    )
    target_layout = source.target_layout
    assert target_layout is not None
    residue_ids = tuple(target_layout.residue_ids or ())
    residue_index = {
        residue_id: index for index, residue_id in enumerate(residue_ids)
    }
    attribute = _TRACK_ATTRIBUTE[track]
    selected_track = getattr(source, attribute)
    assert selected_track is not None
    candidates = [
        residue_index[residue_id]
        for residue_id in effective_eligibility
    ]

    chosen = set(
        sorted(
            candidates,
            key=lambda index: (
                _random_digest(
                    operation="random_mask",
                    effective_seed=effective_seed,
                    draw=0,
                    candidate=residue_ids[index],
                ),
                residue_ids[index],
            ),
        )[:count]
    )
    values = [
        None if index in chosen else value
        for index, value in enumerate(selected_track.values)
    ]
    result = _copy_prompt(
        source,
        tracks={attribute: ResidueTrack(values, None)},
    )
    return result


def _resolved_insert_parameters(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    eligible_chain_ids: tuple[str, ...],
) -> tuple[ProteinPrompt, int, int, tuple[str, ...]]:
    source_layout = prompt.target_layout
    assert source_layout is not None
    if source_layout.length + count > 2_000_000:
        raise ValueError("inserted layout exceeds the supported residue bound")
    chain_order = tuple(source_layout.chain_id.split(","))
    if set(eligible_chain_ids) - set(chain_order):
        raise ValueError("eligible_chain_ids contains an unknown chain")
    effective_eligibility = tuple(sorted(
        eligible_chain_ids or chain_order
    ))
    if count and not effective_eligibility:
        raise ValueError("no eligible chain-local insertion boundary exists")
    return (
        prompt,
        effective_seed,
        count,
        effective_eligibility,
    )


def resolve_random_insert_effective_randomness(
    *,
    inputs: Mapping[str, AdmittedPort],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the canonical effective insertion set before Cache lookup."""
    source: ProteinPrompt = inputs["protein_prompt"].value
    seed = node_parameters["effective_seed"]
    count = node_parameters["count"]
    declared_eligibility: tuple[str, ...] = node_parameters[
        "eligible_chain_ids"
    ]
    source_layout = source.target_layout
    assert source_layout is not None
    chain_order = tuple(source_layout.chain_id.split(","))
    eligibility = tuple(sorted(
        (
            declared_eligibility
            if set(declared_eligibility) - set(chain_order)
            else (declared_eligibility or chain_order)
        )
    ))
    return {
        "effective_seed": seed,
        "count": count,
        "eligible_chain_ids": list(eligibility),
    }


def random_insert_masked(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    eligible_chain_ids: tuple[str, ...],
) -> tuple[ProteinPrompt, ResidueMap]:
    """Insert seeded chain-local nullable residues across every present track."""
    source, effective_seed, count, selected_chains = (
        _resolved_insert_parameters(
            prompt,
            effective_seed=effective_seed,
            count=count,
            eligible_chain_ids=eligible_chain_ids,
        )
    )
    source_layout = source.target_layout
    assert source_layout is not None
    source_ids = tuple(source_layout.residue_ids or ())
    chain_order = tuple(source_layout.chain_id.split(","))

    positions_by_chain: dict[str, list[int]] = {
        chain_id: [] for chain_id in chain_order
    }
    for index, residue_id in enumerate(source_ids):
        positions_by_chain[residue_chain(residue_id)].append(index)
    boundaries: list[tuple[str, int]] = []
    for chain_id in chain_order:
        if chain_id not in selected_chains:
            continue
        chain_positions = positions_by_chain[chain_id]
        if not chain_positions:
            raise ValueError("eligible chain has no residue boundary")
        boundaries.extend(
            [(chain_id, chain_positions[0])]
            + [(chain_id, position + 1) for position in chain_positions]
        )
    if count and not boundaries:
        raise ValueError("no eligible insertion boundary exists")

    boundary_set_digest = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "schema_namespace": _RANDOMNESS_NAMESPACE,
                    "operation": "random_insert_masked",
                    "eligible_boundaries": [
                        {
                            "chain_id": chain_id,
                            "source_position": source_position,
                        }
                        for chain_id, source_position in boundaries
                    ],
                }
            )
        ).hexdigest()
    )
    selections = [
        (
            *boundaries[
                int.from_bytes(
                    _random_digest(
                        operation="random_insert_masked",
                        effective_seed=effective_seed,
                        draw=ordinal,
                        candidate={
                            "eligible_boundaries_digest": boundary_set_digest,
                        },
                    ),
                    "big",
                )
                % len(boundaries)
            ],
            ordinal,
        )
        for ordinal in range(1, count + 1)
    ]
    inserted_ids: dict[int, str] = {}
    for chain_id, _position, ordinal in selections:
        residue_id = f"{chain_id}:masked.{effective_seed}.{ordinal}"
        if residue_id in source_ids or residue_id in inserted_ids.values():
            raise ValueError("generated inserted residue identity collides")
        inserted_ids[ordinal] = residue_id

    chain_rank = {
        chain_id: index for index, chain_id in enumerate(chain_order)
    }
    selections_by_position: dict[int, list[tuple[str, int]]] = {}
    for chain_id, position, ordinal in selections:
        selections_by_position.setdefault(position, []).append(
            (chain_id, ordinal)
        )
    for same_position in selections_by_position.values():
        same_position.sort(key=lambda item: (chain_rank[item[0]], item[1]))

    target_ids: list[str] = []
    mappings: list[tuple[int, int, str]] = []
    target_values_by_attribute: dict[str, list[object]] = {
        attribute: []
        for attribute in _TRACK_ATTRIBUTE.values()
        if getattr(source, attribute) is not None
    }
    for source_position in range(source_layout.length + 1):
        for _chain_id, ordinal in selections_by_position.get(
            source_position,
            (),
        ):
            target_position = len(target_ids)
            target_ids.append(inserted_ids[ordinal])
            mappings.append((-1, target_position, "insert"))
            for values in target_values_by_attribute.values():
                values.append(None)
        if source_position == source_layout.length:
            continue
        target_position = len(target_ids)
        target_ids.append(source_ids[source_position])
        mappings.append((source_position, target_position, "match"))
        for attribute, values in target_values_by_attribute.items():
            track = getattr(source, attribute)
            assert track is not None
            values.append(track.values[source_position])

    target_layout = ResidueLayout(
        chain_id=source_layout.chain_id,
        length=len(target_ids),
        residue_ids=target_ids,
    )
    residue_map = ResidueMap(
        source_layout=source_layout,
        target_layout=target_layout,
        mappings=mappings,
    )
    target_index = {
        residue_id: index for index, residue_id in enumerate(target_ids)
    }
    annotations = FunctionAnnotations([
        FunctionAnnotation(
            label=annotation.label,
            start=target_index[annotation.start_residue_id] + 1,
            end=target_index[annotation.end_residue_id] + 1,
            chain_id=annotation.chain_id,
            start_residue_id=annotation.start_residue_id,
            end_residue_id=annotation.end_residue_id,
            overlap_policy=annotation.overlap_policy,
        )
        for annotation in source.function_annotations.annotations
    ])
    result = ProteinPrompt(
        target_layout=target_layout,
        sequence_track=(
            None
            if source.sequence_track is None
            else ResidueTrack(
                target_values_by_attribute["sequence_track"],
                None,
            )
        ),
        structure_track=(
            None
            if source.structure_track is None
            else ResidueTrack(
                target_values_by_attribute["structure_track"],
                None,
            )
        ),
        structure_visibility_track=(
            None
            if source.structure_visibility_track is None
            else ResidueTrack(
                target_values_by_attribute["structure_visibility_track"],
                None,
            )
        ),
        secondary_structure_track=(
            None
            if source.secondary_structure_track is None
            else ResidueTrack(
                target_values_by_attribute["secondary_structure_track"],
                None,
            )
        ),
        sasa_track=(
            None
            if source.sasa_track is None
            else ResidueTrack(
                target_values_by_attribute["sasa_track"],
                None,
            )
        ),
        function_annotations=annotations,
    )
    return result, residue_map
