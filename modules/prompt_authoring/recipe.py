"""Single pure ProteinPrompt authoring recipe.

All scientific logic that used to be spread across ``authoring._evaluate``
and the micro-node implementations in ``deterministic.py`` /
``stochastic.py`` / ``implementation.py`` lives here as one deterministic
function. Preview and execution both call only :func:`apply_prompt_recipe`,
so there is exactly one implementation of the authoring semantics.

The recipe owns no UI, projection, or graph-materialization concerns: it
takes resolved Python values (sources + an authoring document) and returns
one validated :class:`~datatypes.prompt.ProteinPrompt`. Determinism is the
invariant — every random section is derived from an explicit seed carried
in the document plus the layout/inputs, never from a process-global RNG.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from typing import Any, Literal

from core.catalog.canonical import canonical_json_bytes
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotationTrack,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
    residue_identity_chain,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import (
    NamedAtomCoordinates,
    ResolvedStructureResidueAxis,
)
from modules.residue_data.port_types import CANONICAL_SS8

from .annotations import replace_function_annotations
from .domain import (
    build_layout,
    normalize_replacement,
    override_values,
)
from .prompts import assemble_protein_prompt, validate_protein_prompt


_TRACK_FIELDS: dict[str, str] = {
    "sequence": "sequence",
    "coordinates": "coordinates",
    "secondary_structure": "secondary_structure",
    "sasa": "sasa",
}

_RANDOMNESS_NAMESPACE = "prompt-authoring-effective-randomness/v1"


# --------------------------------------------------------------------------- #
# Baseline construction
# --------------------------------------------------------------------------- #
def _baseline_prompt(
    *,
    sequence_source: ProteinSequence | None,
    structure_source: ResolvedStructureResidueAxis | None,
    prompt_source: ProteinPrompt | None,
    document: Mapping[str, Any],
) -> ProteinPrompt:
    """Resolve the starting Prompt from exactly one admissible source."""
    if prompt_source is not None:
        return prompt_source
    if structure_source is not None:
        return _prompt_from_structure(structure_source)
    if sequence_source is not None:
        return _prompt_from_sequence(sequence_source)
    chains = document.get("chains")
    if not chains:
        raise ValueError(
            "no Prompt source supplied and the document declares no chains"
        )
    layout = build_layout(tuple(chains))
    return ProteinPrompt(
        layout=layout,
        sequence=tuple([None] * layout.length),
        coordinates=tuple([None] * layout.length),
        secondary_structure=None,
        sasa=None,
        function_annotations=(),
    )


def _prompt_from_structure(
    axis: ResolvedStructureResidueAxis,
) -> ProteinPrompt:
    """Convert the authoritative resolved axis into a Prompt.

    The layout is taken verbatim from the axis: it is never rebuilt from
    chain lengths. Coordinates become NamedAtomCoordinates; residues without
    admitted coordinates receive None.
    """
    layout = axis.layout
    sequence = tuple(axis.sequence)
    if len(sequence) != layout.length:
        raise ValueError(
            "resolved axis sequence length does not match its layout"
        )
    coordinates: list[NamedAtomCoordinates | None] = []
    for residue_id in layout.residue_ids:
        try:
            atoms = axis.coordinates_for(residue_id)
        except KeyError:
            coordinates.append(None)
            continue
        mapping = {atom.atom_name: atom.coordinate for atom in atoms}
        coordinates.append(
            NamedAtomCoordinates.from_mapping(mapping) if mapping else None
        )
    return ProteinPrompt(
        layout=layout,
        sequence=sequence,
        coordinates=tuple(coordinates),
        secondary_structure=None,
        sasa=None,
        function_annotations=(),
    )


def _prompt_from_sequence(sequence_source: ProteinSequence) -> ProteinPrompt:
    if sequence_source.residue_ids is not None:
        layout = ResidueLayout(tuple(sequence_source.residue_ids))
    else:
        layout = ResidueLayout(
            tuple(f"A:{index + 1}" for index in range(len(sequence_source)))
        )
    if layout.length != len(sequence_source.sequence):
        raise ValueError(
            "sequence source residue identities do not match sequence length"
        )
    return ProteinPrompt(
        layout=layout,
        sequence=tuple(sequence_source.sequence),
        coordinates=tuple([None] * layout.length),
        secondary_structure=None,
        sasa=None,
        function_annotations=(),
    )


# --------------------------------------------------------------------------- #
# Identity-preserving reindex (insert / delete, shared identities preserved)
# --------------------------------------------------------------------------- #
def _reindex_to_target(
    prompt: ProteinPrompt,
    target_residues: Sequence[Mapping[str, Any]] | None,
) -> ProteinPrompt:
    """Reindex the Prompt onto the document's ordered target identities."""
    if not target_residues:
        return prompt
    baseline_ids = set(prompt.layout.residue_ids)
    target_ids: list[str] = []
    for item in target_residues:
        residue_id = item["residue_id"]
        origin = item["origin"]
        if origin == "source":
            if residue_id not in baseline_ids:
                raise ValueError(
                    f"target residue {residue_id!r} is not in the source layout"
                )
        elif origin == "inserted":
            if residue_id in baseline_ids:
                raise ValueError(
                    f"inserted residue {residue_id!r} collides with a source "
                    "residue"
                )
        else:
            raise ValueError(f"unknown target residue origin {origin!r}")
        target_ids.append(residue_id)
    if len(set(target_ids)) != len(target_ids):
        raise ValueError("target_residues contains duplicate residue identities")
    layout = ResidueLayout(tuple(target_ids))
    source_index = {
        residue_id: index
        for index, residue_id in enumerate(prompt.layout.residue_ids)
    }

    def remap(values: Sequence[Any] | None) -> tuple[Any | None, ...] | None:
        if values is None:
            return None
        return tuple(
            values[source_index[residue_id]] if residue_id in source_index else None
            for residue_id in target_ids
        )

    target_set = set(target_ids)
    annotations = tuple(
        annotation
        for annotation in prompt.function_annotations
        if annotation.start_residue_id in target_set
        and annotation.end_residue_id in target_set
    )
    return ProteinPrompt(
        layout=layout,
        sequence=remap(prompt.sequence),  # type: ignore[arg-type]
        coordinates=remap(prompt.coordinates),  # type: ignore[arg-type]
        secondary_structure=remap(prompt.secondary_structure),
        sasa=remap(prompt.sasa),
        function_annotations=annotations,
    )


# --------------------------------------------------------------------------- #
# SS8 admission normalization (spec §6.1)
# --------------------------------------------------------------------------- #
def _normalize_ss8_token(value: object) -> str | None:
    """Normalize one public SS8 admission token to the canonical value.

    ``-`` becomes ``C``; ``_`` becomes missing (None); canonical states pass
    through. Raw DSSP ``P`` is invalid prompt input and raises.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("secondary-structure value must be text")
    if value == "-":
        return "C"
    if value == "_":
        return None
    if value == "P":
        raise ValueError("raw DSSP state P is not a valid prompt input")
    if value not in CANONICAL_SS8:
        raise ValueError(f"invalid SS8 token {value!r}")
    return value


# --------------------------------------------------------------------------- #
# Rigid transforms
# --------------------------------------------------------------------------- #
def _validate_rigid(transform: Mapping[str, Any]) -> None:
    matrix = transform["rotation_matrix"]
    orthonormal = all(
        math.isclose(
            math.fsum(matrix[row][left] * matrix[row][right] for row in range(3)),
            1.0 if left == right else 0.0,
            rel_tol=0.0,
            abs_tol=1e-8,
        )
        for left in range(3)
        for right in range(3)
    )
    determinant = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
    if not orthonormal or not math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=1e-8):
        raise ValueError("rigid transform rotation matrix is not a proper rotation")


def _apply_rigid(
    coordinates: NamedAtomCoordinates,
    transform: Mapping[str, Any],
) -> NamedAtomCoordinates:
    matrix = transform["rotation_matrix"]
    origin = transform["origin"]
    translation = transform["translation"]
    replaced: dict[str, tuple[float, float, float]] = {}
    for atom_name, (x, y, z) in coordinates.atoms:
        px = x - origin[0]
        py = y - origin[1]
        pz = z - origin[2]
        rx = (
            matrix[0][0] * px
            + matrix[0][1] * py
            + matrix[0][2] * pz
            + origin[0]
            + translation[0]
        )
        ry = (
            matrix[1][0] * px
            + matrix[1][1] * py
            + matrix[1][2] * pz
            + origin[1]
            + translation[1]
        )
        rz = (
            matrix[2][0] * px
            + matrix[2][1] * py
            + matrix[2][2] * pz
            + origin[2]
            + translation[2]
        )
        replaced[atom_name] = (float(rx), float(ry), float(rz))
    return NamedAtomCoordinates.from_mapping(replaced)


# --------------------------------------------------------------------------- #
# Track overrides (sparse edits + rigid transforms)
# --------------------------------------------------------------------------- #
def _collect_overrides(
    prompt: ProteinPrompt,
    track_edits: Sequence[Mapping[str, Any]] | None,
    rigid_transforms: Sequence[Mapping[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]]:
    overrides: dict[str, list[dict[str, Any]]] = {
        track: [] for track in _TRACK_FIELDS
    }
    for edit in track_edits or ():
        track = edit["track"]
        action = edit["action"]
        if action == "preserve":
            continue
        residue_id = edit["residue_id"]
        if action == "clear":
            overrides[track].append(
                {"action": "clear", "residue_id": residue_id}
            )
        elif action == "replace":
            value = edit["value"]
            if track == "secondary_structure":
                value = _normalize_ss8_token(value)
                if value is None:
                    overrides[track].append(
                        {"action": "clear", "residue_id": residue_id}
                    )
                    continue
            overrides[track].append(
                {
                    "action": "replace",
                    "residue_id": residue_id,
                    "value": value,
                }
            )
        else:
            raise ValueError(f"unknown track edit action {action!r}")
    for transform in rigid_transforms or ():
        _validate_rigid(transform)
        for residue_id in transform["residue_ids"]:
            index = prompt.layout.residue_ids.index(residue_id)
            coordinates = prompt.coordinates[index]
            if coordinates is None:
                raise ValueError(
                    f"rigid transform residue {residue_id!r} has no coordinates"
                )
            overrides["coordinates"].append(
                {
                    "action": "replace",
                    "residue_id": residue_id,
                    "value": _apply_rigid(coordinates, transform),
                }
            )
    return overrides


def _apply_track_overrides(
    prompt: ProteinPrompt,
    overrides_by_track: Mapping[str, Sequence[Mapping[str, Any]]],
) -> ProteinPrompt:
    fields: dict[str, Any] = {
        "sequence": prompt.sequence,
        "coordinates": prompt.coordinates,
        "secondary_structure": prompt.secondary_structure,
        "sasa": prompt.sasa,
    }
    for track, raw_overrides in overrides_by_track.items():
        if not raw_overrides:
            continue
        current = fields[track]
        if current is None:
            current = tuple([None] * prompt.layout.length)
        changed = override_values(
            current,
            prompt.layout,
            tuple(raw_overrides),
            kind=track,
        )
        if fields[track] is None and all(item is None for item in changed):
            changed = None  # keep whole-track absent
        fields[track] = changed
    return ProteinPrompt(
        layout=prompt.layout,
        sequence=fields["sequence"],  # type: ignore[arg-type]
        coordinates=fields["coordinates"],  # type: ignore[arg-type]
        secondary_structure=fields["secondary_structure"],  # type: ignore[arg-type]
        sasa=fields["sasa"],  # type: ignore[arg-type]
        function_annotations=prompt.function_annotations,
    )


# --------------------------------------------------------------------------- #
# Deterministic randomness (seeded, provider-free)
# --------------------------------------------------------------------------- #
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


def normalize_random_mask_effective_randomness(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    track: str,
    eligible_residue_ids: Sequence[str],
) -> dict[str, Any]:
    """Canonicalize the random-mask eligibility set before selection."""
    if track not in _TRACK_FIELDS:
        raise ValueError(f"unknown random mask track {track!r}")
    field = _TRACK_FIELDS[track]
    values = getattr(prompt, field)
    if values is None:
        raise ValueError(f"random mask requires a present {track} track")
    residue_ids = prompt.layout.residue_ids
    index = {residue_id: position for position, residue_id in enumerate(residue_ids)}
    eligible = tuple(eligible_residue_ids) or tuple(residue_ids)
    unknown = set(eligible) - set(index)
    if unknown:
        raise ValueError("eligible_residue_ids contains an unknown residue")
    assigned = tuple(
        residue_id for residue_id in eligible if values[index[residue_id]] is not None
    )
    if count > len(assigned):
        raise ValueError("random mask count exceeds assigned eligible positions")
    return {
        "effective_seed": effective_seed,
        "count": count,
        "track": track,
        "eligible_residue_ids": list(assigned),
    }


def resolve_random_mask_effective_randomness(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    track: str,
    eligible_residue_ids: Sequence[str],
) -> dict[str, Any]:
    """Resolver-shaped wrapper kept importable by ``package`` bindings."""
    return normalize_random_mask_effective_randomness(
        prompt,
        effective_seed=effective_seed,
        count=count,
        track=track,
        eligible_residue_ids=eligible_residue_ids,
    )


def _apply_random_mask(
    prompt: ProteinPrompt,
    operation: Mapping[str, Any],
) -> ProteinPrompt:
    effective = normalize_random_mask_effective_randomness(
        prompt,
        effective_seed=operation["seed"],
        count=operation["count"],
        track=operation["track"],
        eligible_residue_ids=operation.get("eligible_residue_ids") or (),
    )
    field = _TRACK_FIELDS[effective["track"]]
    values = list(getattr(prompt, field))
    residue_ids = prompt.layout.residue_ids
    chosen = set(
        sorted(
            effective["eligible_residue_ids"],
            key=lambda residue_id: (
                _random_digest(
                    operation="random_mask",
                    effective_seed=effective["effective_seed"],
                    draw=0,
                    candidate=residue_id,
                ),
                residue_id,
            ),
        )[: effective["count"]]
    )
    for residue_id in chosen:
        values[residue_ids.index(residue_id)] = None
    return _with_track(prompt, effective["track"], tuple(values))


def normalize_random_insert_effective_randomness(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    eligible_chain_ids: Sequence[str],
) -> dict[str, Any]:
    """Canonicalize the random-insertion eligibility set before selection."""
    chain_order = prompt.layout.chain_ids
    eligible = tuple(eligible_chain_ids) or tuple(chain_order)
    unknown = set(eligible) - set(chain_order)
    if unknown:
        raise ValueError("eligible_chain_ids contains an unknown chain")
    populated = {
        residue_identity_chain(residue_id)
        for residue_id in prompt.layout.residue_ids
    }
    missing = tuple(chain for chain in eligible if chain not in populated)
    if missing:
        raise ValueError("eligible chain has no residue boundary")
    return {
        "effective_seed": effective_seed,
        "count": count,
        "eligible_chain_ids": sorted(eligible),
    }


def resolve_random_insert_effective_randomness(
    prompt: ProteinPrompt,
    *,
    effective_seed: int,
    count: int,
    eligible_chain_ids: Sequence[str],
) -> dict[str, Any]:
    """Resolver-shaped wrapper kept importable by ``package`` bindings."""
    return normalize_random_insert_effective_randomness(
        prompt,
        effective_seed=effective_seed,
        count=count,
        eligible_chain_ids=eligible_chain_ids,
    )


def _apply_random_insert(
    prompt: ProteinPrompt,
    operation: Mapping[str, Any],
) -> ProteinPrompt:
    effective = normalize_random_insert_effective_randomness(
        prompt,
        effective_seed=operation["seed"],
        count=operation["count"],
        eligible_chain_ids=operation.get("eligible_chain_ids") or (),
    )
    eligible_chains = tuple(effective["eligible_chain_ids"])
    source_ids = prompt.layout.residue_ids
    chain_order = prompt.layout.chain_ids
    positions_by_chain: dict[str, list[int]] = {}
    for position, residue_id in enumerate(source_ids):
        positions_by_chain.setdefault(
            residue_identity_chain(residue_id), []
        ).append(position)
    boundaries: list[tuple[str, int]] = []
    for chain_id in chain_order:
        if chain_id not in eligible_chains:
            continue
        chain_positions = positions_by_chain[chain_id]
        boundaries.extend(
            [(chain_id, chain_positions[0])]
            + [(chain_id, position + 1) for position in chain_positions]
        )
    if not boundaries:
        raise ValueError("no eligible chain-local insertion boundary exists")

    boundary_digest = "sha256:" + hashlib.sha256(
        canonical_json_bytes(
            {
                "schema_namespace": _RANDOMNESS_NAMESPACE,
                "operation": "random_insert_masked",
                "eligible_boundaries": [
                    {"chain_id": chain_id, "source_position": source_position}
                    for chain_id, source_position in boundaries
                ],
            }
        )
    ).hexdigest()

    selections: list[tuple[str, int, int]] = []
    for ordinal in range(1, effective["count"] + 1):
        digest = _random_digest(
            operation="random_insert_masked",
            effective_seed=effective["effective_seed"],
            draw=ordinal,
            candidate={"eligible_boundaries_digest": boundary_digest},
        )
        boundary = boundaries[int.from_bytes(digest, "big") % len(boundaries)]
        selections.append((boundary[0], boundary[1], ordinal))

    inserted_ids: dict[int, str] = {}
    for chain_id, _position, ordinal in selections:
        residue_id = f"{chain_id}:masked.{effective['effective_seed']}.{ordinal}"
        if residue_id in source_ids:
            raise ValueError(
                f"generated inserted residue {residue_id!r} collides"
            )
        inserted_ids[ordinal] = residue_id

    chain_rank = {chain_id: index for index, chain_id in enumerate(chain_order)}
    by_position: dict[int, list[tuple[str, int]]] = {}
    for chain_id, position, ordinal in selections:
        by_position.setdefault(position, []).append((chain_id, ordinal))
    for same_position in by_position.values():
        same_position.sort(key=lambda item: (chain_rank[item[0]], item[1]))

    target_ids: list[str] = []
    new_values: dict[str, list[Any]] = {field: [] for field in _TRACK_FIELDS.values()}
    present_fields = {
        field: getattr(prompt, field) is not None for field in _TRACK_FIELDS.values()
    }
    for position in range(prompt.layout.length + 1):
        for chain_id, ordinal in by_position.get(position, ()):
            target_ids.append(inserted_ids[ordinal])
            for field in _TRACK_FIELDS.values():
                new_values[field].append(None)
        if position == prompt.layout.length:
            break
        residue_id = source_ids[position]
        target_ids.append(residue_id)
        for field in _TRACK_FIELDS.values():
            source_values = getattr(prompt, field)
            new_values[field].append(
                None if source_values is None else source_values[position]
            )

    layout = ResidueLayout(tuple(target_ids))
    return ProteinPrompt(
        layout=layout,
        sequence=tuple(new_values["sequence"]),  # type: ignore[arg-type]
        coordinates=tuple(new_values["coordinates"]),  # type: ignore[arg-type]
        secondary_structure=(
            tuple(new_values["secondary_structure"])
            if present_fields["secondary_structure"]
            else None
        ),
        sasa=(
            tuple(new_values["sasa"]) if present_fields["sasa"] else None
        ),
        function_annotations=tuple(prompt.function_annotations),
    )


def _with_track(
    prompt: ProteinPrompt,
    track: str,
    values: tuple[Any | None, ...],
) -> ProteinPrompt:
    if track == "sequence":
        return ProteinPrompt(
            layout=prompt.layout,
            sequence=values,  # type: ignore[arg-type]
            coordinates=prompt.coordinates,
            secondary_structure=prompt.secondary_structure,
            sasa=prompt.sasa,
            function_annotations=prompt.function_annotations,
        )
    if track == "coordinates":
        return ProteinPrompt(
            layout=prompt.layout,
            sequence=prompt.sequence,
            coordinates=values,  # type: ignore[arg-type]
            secondary_structure=prompt.secondary_structure,
            sasa=prompt.sasa,
            function_annotations=prompt.function_annotations,
        )
    if track == "secondary_structure":
        return ProteinPrompt(
            layout=prompt.layout,
            sequence=prompt.sequence,
            coordinates=prompt.coordinates,
            secondary_structure=values,  # type: ignore[arg-type]
            sasa=prompt.sasa,
            function_annotations=prompt.function_annotations,
        )
    return ProteinPrompt(
        layout=prompt.layout,
        sequence=prompt.sequence,
        coordinates=prompt.coordinates,
        secondary_structure=prompt.secondary_structure,
        sasa=values,  # type: ignore[arg-type]
        function_annotations=prompt.function_annotations,
    )


# --------------------------------------------------------------------------- #
# Function annotations
# --------------------------------------------------------------------------- #
def _apply_function_annotations(
    prompt: ProteinPrompt,
    document: Mapping[str, Any],
) -> ProteinPrompt:
    raw = document.get("function_annotations") or ()
    if not raw:
        return prompt
    overlap_policy = document.get("overlap_policy", "allow")
    annotations = replace_function_annotations(
        prompt.layout,
        tuple(raw),
        overlap_policy=overlap_policy,
    )
    return ProteinPrompt(
        layout=prompt.layout,
        sequence=prompt.sequence,
        coordinates=prompt.coordinates,
        secondary_structure=prompt.secondary_structure,
        sasa=prompt.sasa,
        function_annotations=annotations,
    )


# --------------------------------------------------------------------------- #
# Source merges (adopt / preserve per track)
# --------------------------------------------------------------------------- #
def _merge_one(
    target: ProteinPrompt,
    source: ProteinPrompt,
    merge: Mapping[str, Any],
) -> ProteinPrompt:
    track_decisions = merge["track_decisions"]
    correspondence = merge.get("correspondence") or ()
    matched: list[tuple[str, str]] = []
    for row in correspondence:
        if row.get("disposition") == "match":
            matched.append(
                (row["source_residue_id"], row["target_residue_id"])
            )
    source_index = {
        residue_id: index
        for index, residue_id in enumerate(source.layout.residue_ids)
    }
    target_index = {
        residue_id: index
        for index, residue_id in enumerate(target.layout.residue_ids)
    }
    for source_residue_id, target_residue_id in matched:
        if source_residue_id not in source_index:
            raise ValueError("merge correspondence source residue is unknown")
        if target_residue_id not in target_index:
            raise ValueError("merge correspondence target residue is unknown")
    source_to_target = {source_id: target_id for source_id, target_id in matched}

    def merged_track(field: str, decision: str) -> Any:
        target_values = getattr(target, field)
        source_values = getattr(source, field)
        if decision == "preserve":
            return target_values
        if source_values is None:
            return target_values
        base: list[Any] = (
            list(target_values)
            if target_values is not None
            else [None] * target.layout.length
        )
        for source_id, target_id in matched:
            base[target_index[target_id]] = source_values[source_index[source_id]]
        return tuple(base)

    sequence = merged_track("sequence", track_decisions["sequence"])
    coordinates = merged_track("coordinates", track_decisions["coordinates"])
    secondary_structure = merged_track(
        "secondary_structure", track_decisions["secondary_structure"]
    )
    sasa = merged_track("sasa", track_decisions["sasa"])

    if track_decisions["function_annotations"] == "preserve":
        annotations = target.function_annotations
    else:
        mapped: list[FunctionAnnotation] = []
        for annotation in source.function_annotations:
            start = source_to_target.get(annotation.start_residue_id)
            end = source_to_target.get(annotation.end_residue_id)
            if start is None or end is None:
                raise ValueError(
                    "merge would lose a function annotation interval"
                )
            mapped.append(
                FunctionAnnotation(
                    label=annotation.label,
                    start_residue_id=start,
                    end_residue_id=end,
                )
            )
        annotations = tuple(mapped)

    return ProteinPrompt(
        layout=target.layout,
        sequence=sequence,  # type: ignore[arg-type]
        coordinates=coordinates,  # type: ignore[arg-type]
        secondary_structure=secondary_structure,  # type: ignore[arg-type]
        sasa=sasa,  # type: ignore[arg-type]
        function_annotations=annotations,
    )


def _apply_merges(
    prompt: ProteinPrompt,
    merge_sources: Sequence[ProteinPrompt],
    document: Mapping[str, Any],
) -> ProteinPrompt:
    for merge in document.get("source_merges") or ():
        source_index = merge["source_index"]
        if source_index < 0 or source_index >= len(merge_sources):
            raise ValueError(f"merge source index {source_index} out of range")
        prompt = _merge_one(prompt, merge_sources[source_index], merge)
    return prompt


# --------------------------------------------------------------------------- #
# Single entry point
# --------------------------------------------------------------------------- #
def apply_prompt_recipe(
    *,
    sequence_source: ProteinSequence | None,
    structure_source: ResolvedStructureResidueAxis | None,
    prompt_source: ProteinPrompt | None,
    merge_sources: Sequence[ProteinPrompt],
    document: Mapping[str, Any],
) -> ProteinPrompt:
    """Apply one authoring document to the resolved sources.

    The document holds the editing intent only; sources are resolved by the
    caller. Determinism is guaranteed: every random section derives from the
    explicit seed recorded in the document plus the resolved layout/inputs.
    """
    if document is None:
        raise ValueError("authoring document is required")
    prompt = _baseline_prompt(
        sequence_source=sequence_source,
        structure_source=structure_source,
        prompt_source=prompt_source,
        document=document,
    )
    prompt = _reindex_to_target(prompt, document.get("target_residues"))
    # Random insertions create new masked identities; track edits may address
    # them, so insertions run before edits and masks run after them.
    for operation in document.get("random_operations") or ():
        if operation["kind"] == "insert":
            prompt = _apply_random_insert(prompt, operation)
    overrides = _collect_overrides(
        prompt,
        document.get("track_edits"),
        document.get("rigid_transforms"),
    )
    prompt = _apply_track_overrides(prompt, overrides)
    for operation in document.get("random_operations") or ():
        if operation["kind"] == "mask":
            prompt = _apply_random_mask(prompt, operation)
    prompt = _apply_function_annotations(prompt, document)
    prompt = _apply_merges(prompt, merge_sources or (), document)
    return validate_protein_prompt(prompt)
