"""Single pure ProteinPrompt authoring recipe.

All scientific logic that used to be spread across ``authoring._evaluate``
and the micro-node implementations in ``deterministic.py`` /
``stochastic.py`` / ``implementation.py`` lives here as one deterministic
function. Preview and execution both call only :func:`apply_prompt_recipe`,
so there is exactly one implementation of the authoring semantics.

The recipe owns no UI, projection, or graph-materialization concerns: it
takes resolved Python values (sources + an authoring document) and returns
one :class:`~datatypes.prompt.ProteinPrompt`. Determinism is the
invariant — every random section is derived from an explicit seed carried
in the document plus the layout/inputs, never from a process-global RNG.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import hashlib
import math
from typing import Any

from datatypes.i_json import canonical_json_bytes
from datatypes.prompt import (
    FunctionAnnotation,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    residue_identity_chain,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import (
    NamedAtomCoordinates,
    ResolvedStructureResidueAxis,
)
from modules.residue_data.elements import CANONICAL_SS8

from .annotations import replace_function_annotations
from .domain import (
    build_layout,
    override_values,
)


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
    sources = (sequence_source, structure_source, prompt_source)
    if sum(source is not None for source in sources) > 1:
        raise ValueError(
            "prompt authoring accepts at most one primary source"
        )
    if prompt_source is not None:
        return prompt_source
    if structure_source is not None:
        return _prompt_from_structure(structure_source)
    if sequence_source is not None:
        return _prompt_from_sequence(sequence_source, document)
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
        atoms = axis.coordinates_for(residue_id)
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


def _prompt_from_sequence(
    sequence_source: ProteinSequence,
    document: Mapping[str, Any],
) -> ProteinPrompt:
    chains = document.get("chains")
    if not chains:
        raise ValueError("sequence-source authoring requires declared chains")
    declared_layout = build_layout(tuple(chains))
    if sequence_source.residue_ids is not None:
        layout = ResidueLayout(tuple(sequence_source.residue_ids))
        actual = tuple(
            (
                chain_id,
                sum(
                    residue_identity_chain(residue_id) == chain_id
                    for residue_id in layout.residue_ids
                ),
            )
            for chain_id in layout.chain_ids
        )
        declared = tuple(
            (chain["chain_id"], chain["length"]) for chain in chains
        )
        if actual != declared:
            raise ValueError(
                "sequence source residue identities do not match declared chains"
            )
    else:
        layout = declared_layout
    if layout.length != len(sequence_source.sequence):
        raise ValueError(
            "sequence source length does not match declared chains"
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
    *,
    replace_annotations: bool,
    declared_chains: frozenset[str],
) -> ProteinPrompt:
    """Reindex within the initial recipe's explicitly declared chain scope."""
    if target_residues is None:
        return prompt
    baseline_ids = set(prompt.layout.residue_ids)
    baseline_index = {
        residue_id: index
        for index, residue_id in enumerate(prompt.layout.residue_ids)
    }
    target_ids: list[str] = []
    source_positions: list[int] = []
    for item in target_residues:
        residue_id = item["residue_id"]
        origin = item["origin"]
        if origin == "source":
            if residue_id not in baseline_ids:
                raise ValueError(
                    f"target residue {residue_id!r} is not in the source layout"
                )
            source_positions.append(baseline_index[residue_id])
        elif origin == "inserted":
            if residue_id in baseline_ids:
                raise ValueError(
                    f"inserted residue {residue_id!r} collides with a source "
                    "residue"
                )
            if residue_identity_chain(residue_id) not in declared_chains:
                raise ValueError(
                    f"inserted residue {residue_id!r} is outside declared chains"
                )
        else:
            raise ValueError(f"unknown target residue origin {origin!r}")
        target_ids.append(residue_id)
    if len(set(target_ids)) != len(target_ids):
        raise ValueError("target_residues contains duplicate residue identities")
    if source_positions != sorted(source_positions):
        raise ValueError("target_residues reorders source residue identities")
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

    target_index = {
        residue_id: index for index, residue_id in enumerate(target_ids)
    }
    annotations: list[FunctionAnnotation] = []
    for annotation in prompt.function_annotations:
        start = baseline_index[annotation.start_residue_id]
        end = baseline_index[annotation.end_residue_id]
        interval = prompt.layout.residue_ids[start : end + 1]
        if any(residue_id not in target_index for residue_id in interval):
            if replace_annotations:
                continue
            raise ValueError(
                "target layout would truncate an inherited function "
                "annotation interval"
            )
        positions = tuple(target_index[residue_id] for residue_id in interval)
        if positions != tuple(range(positions[0], positions[0] + len(positions))):
            if replace_annotations:
                continue
            raise ValueError(
                "target layout would split an inherited function "
                "annotation interval"
            )
        annotations.append(annotation)
    return ProteinPrompt(
        layout=layout,
        sequence=remap(prompt.sequence),  # type: ignore[arg-type]
        coordinates=remap(prompt.coordinates),  # type: ignore[arg-type]
        secondary_structure=remap(prompt.secondary_structure),
        sasa=remap(prompt.sasa),
        function_annotations=tuple(annotations),
    )


# --------------------------------------------------------------------------- #
# SS8 admission normalization (spec §6.1)
# --------------------------------------------------------------------------- #
def _normalize_ss8_token(value: object) -> str | None:
    """Normalize one public SS8 admission token to the canonical value.

    ``-`` becomes ``C``; canonical states pass through. Raw DSSP-only tokens
    are invalid prompt input and raise.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("secondary-structure value must be text")
    if value == "-":
        return "C"
    if value in {"_", "P"}:
        raise ValueError(f"raw DSSP state {value} is not a valid prompt input")
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
    track_edits: Sequence[Mapping[str, Any]] | None,
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
            elif track == "sasa" and type(value) is int:
                value = float(value)
            overrides[track].append(
                {
                    "action": "replace",
                    "residue_id": residue_id,
                    "value": value,
                }
            )
        else:
            raise ValueError(f"unknown track edit action {action!r}")
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
        fields[track] = changed
    return ProteinPrompt(
        layout=prompt.layout,
        sequence=fields["sequence"],  # type: ignore[arg-type]
        coordinates=fields["coordinates"],  # type: ignore[arg-type]
        secondary_structure=fields["secondary_structure"],  # type: ignore[arg-type]
        sasa=fields["sasa"],  # type: ignore[arg-type]
        function_annotations=prompt.function_annotations,
    )


def _apply_rigid_transforms(
    prompt: ProteinPrompt,
    transforms: Sequence[Mapping[str, Any]],
) -> ProteinPrompt:
    coordinates = list(prompt.coordinates)
    for transform in transforms:
        _validate_rigid(transform)
        for residue_id in transform["residue_ids"]:
            index = prompt.layout.residue_ids.index(residue_id)
            current = coordinates[index]
            if current is None:
                raise ValueError(
                    f"rigid transform residue {residue_id!r} has no coordinates"
                )
            coordinates[index] = _apply_rigid(current, transform)
    return replace(prompt, coordinates=tuple(coordinates))


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
) -> tuple[ProteinPrompt, tuple[str, ...]]:
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
    selected = tuple(
        residue_id for residue_id in residue_ids if residue_id in chosen
    )
    for residue_id in selected:
        values[residue_ids.index(residue_id)] = None
    return _with_track(prompt, effective["track"], tuple(values)), selected


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
    *,
    operation_index: int,
) -> tuple[ProteinPrompt, tuple[str, ...]]:
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
        residue_id = (
            f"{chain_id}:masked.{effective['effective_seed']}."
            f"{operation_index}.{ordinal}"
        )
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
    result = ProteinPrompt(
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
    inserted_id_set = set(inserted_ids.values())
    return result, tuple(
        residue_id
        for residue_id in result.layout.residue_ids
        if residue_id in inserted_id_set
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
    if "function_annotations" not in document:
        return prompt
    raw = document["function_annotations"]
    annotations = replace_function_annotations(
        prompt.layout,
        tuple(raw),
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
# Source merges (explicit residue × track adoption)
# --------------------------------------------------------------------------- #
def _annotation_intent(value: Mapping[str, Any]) -> FunctionAnnotation:
    return FunctionAnnotation(
        label=value["label"],
        start_residue_id=value["start_residue_id"],
        end_residue_id=value["end_residue_id"],
    )


def _merge_one(
    target: ProteinPrompt,
    source: ProteinPrompt,
    merge: Mapping[str, Any],
    *,
    declared_chains: frozenset[str],
) -> ProteinPrompt:
    matched: list[tuple[str, str]] = []
    ordered_source_ids: list[str] = []
    ordered_target_ids: list[str] = []
    expanded_targets: list[dict[str, str]] = []
    for row in merge["correspondence"]:
        disposition = row["disposition"]
        if disposition in {"match", "insert"}:
            source_id, target_id = row["source_residue_id"], row["target_residue_id"]
            matched.append((source_id, target_id))
            ordered_source_ids.append(source_id)
            if disposition == "match":
                ordered_target_ids.append(target_id)
            expanded_targets.append({
                "residue_id": target_id,
                "origin": "inserted" if disposition == "insert" else "source",
            })
        elif disposition == "source_gap":
            ordered_source_ids.append(row["source_residue_id"])
        else:  # target_gap, admitted by the document contract
            target_id = row["target_residue_id"]
            ordered_target_ids.append(target_id)
            expanded_targets.append({"residue_id": target_id, "origin": "source"})
    if tuple(ordered_source_ids) != source.layout.residue_ids:
        raise ValueError("merge correspondence must cover source residues exactly once in order")
    if tuple(ordered_target_ids) != target.layout.residue_ids:
        raise ValueError("merge correspondence must cover target residues exactly once in order")

    retained_annotations = list(target.function_annotations)
    for intent in merge["remove_annotations"]:
        annotation = _annotation_intent(intent)
        if annotation not in retained_annotations:
            raise ValueError("merge removal must reference an exact current target annotation")
        retained_annotations.remove(annotation)
    target = _reindex_to_target(
        replace(target, function_annotations=tuple(retained_annotations)),
        expanded_targets,
        replace_annotations=False,
        declared_chains=declared_chains,
    )
    source_index = {value: index for index, value in enumerate(source.layout.residue_ids)}
    target_index = {value: index for index, value in enumerate(target.layout.residue_ids)}
    source_to_target = dict(matched)
    fields = {field: getattr(target, field) for field in _TRACK_FIELDS}
    adopted_tracks: set[str] = set()
    for adoption in merge["track_adoptions"]:
        field = adoption["track"]
        if field in adopted_tracks:
            raise ValueError(f"merge track {field!r} must have one adoption selection")
        adopted_tracks.add(field)
        source_values = getattr(source, field)
        if source_values is None:
            raise ValueError(f"cannot adopt absent source track {field!r}")
        current = fields[field]
        values = list(current) if current is not None else None
        for source_id in adoption["source_residue_ids"]:
            if source_id not in source_to_target:
                raise ValueError(f"adopted source residue {source_id!r} has no target correspondence")
            value = source_values[source_index[source_id]]
            if value is not None or adoption["mask_policy"] == "adopt":
                if values is None:
                    values = [None] * target.layout.length
                values[target_index[source_to_target[source_id]]] = value
        fields[field] = tuple(values) if values is not None else None

    annotations = list(target.function_annotations)
    for intent in merge["adopt_annotations"]:
        annotation = _annotation_intent(intent)
        if annotation not in source.function_annotations:
            raise ValueError("merge adoption must reference an exact source annotation")
        interval = source.layout.residue_ids[
            source_index[annotation.start_residue_id] : source_index[annotation.end_residue_id] + 1
        ]
        if any(value not in source_to_target for value in interval):
            raise ValueError("merge would lose a function annotation interval")
        mapped = tuple(source_to_target[value] for value in interval)
        positions = tuple(target_index[value] for value in mapped)
        if positions != tuple(range(positions[0], positions[0] + len(positions))):
            raise ValueError("merge function annotation must map to one contiguous interval")
        if len({residue_identity_chain(value) for value in mapped}) != 1:
            raise ValueError("merge function annotation must map within one target chain")
        annotations.append(FunctionAnnotation(annotation.label, mapped[0], mapped[-1]))
    return ProteinPrompt(
        layout=target.layout,
        sequence=fields["sequence"],
        coordinates=fields["coordinates"],
        secondary_structure=fields["secondary_structure"],
        sasa=fields["sasa"],
        function_annotations=replace_function_annotations(target.layout, tuple(
            {"label": item.label, "start_residue_id": item.start_residue_id, "end_residue_id": item.end_residue_id}
            for item in annotations
        )),
    )


def _apply_merges(
    prompt: ProteinPrompt,
    merge_sources: Sequence[ProteinPrompt],
    document: Mapping[str, Any],
    *,
    declared_chains: frozenset[str],
) -> tuple[ProteinPrompt, tuple[ProteinPrompt, ...]]:
    targets: list[ProteinPrompt] = []
    for merge in document.get("source_merges") or ():
        source_index = merge["source_index"]
        if source_index < 0 or source_index >= len(merge_sources):
            raise ValueError(f"merge source index {source_index} out of range")
        targets.append(prompt)
        prompt = _merge_one(prompt, merge_sources[source_index], merge, declared_chains=declared_chains)
    targets.append(prompt)
    return prompt, tuple(targets)


# --------------------------------------------------------------------------- #
# Single entry point
# --------------------------------------------------------------------------- #
def _evaluate_prompt_recipe(
    *,
    sequence_source: ProteinSequence | None,
    structure_source: ResolvedStructureResidueAxis | None,
    prompt_source: ProteinPrompt | None,
    merge_sources: Sequence[ProteinPrompt],
    document: Mapping[str, Any],
) -> tuple[ProteinPrompt, tuple[Mapping[str, Any], ...], tuple[ProteinPrompt, ...]]:
    """Apply one document and retain the random choices made by that run.

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
    declared_chains = frozenset(prompt.layout.chain_ids)
    prompt = _reindex_to_target(
        prompt,
        document.get("target_residues"),
        replace_annotations="function_annotations" in document,
        declared_chains=declared_chains,
    )
    operations = tuple(document.get("random_operations") or ())
    for operation in operations:
        if operation["kind"] not in {"insert", "mask"}:
            raise ValueError(f"unknown random operation kind {operation['kind']!r}")
    traces: dict[int, Mapping[str, Any]] = {}
    # Random insertions create new masked identities; track edits may address
    # them, so insertions run before edits and masks run after them.
    for operation_index, operation in enumerate(operations):
        if operation["kind"] == "insert":
            prompt, residue_ids = _apply_random_insert(
                prompt,
                operation,
                operation_index=operation_index,
            )
            traces[operation_index] = {
                "operation_index": operation_index,
                "kind": "insert",
                "residue_ids": residue_ids,
            }
    prompt, merge_targets = _apply_merges(prompt, merge_sources or (), document, declared_chains=declared_chains)
    overrides = _collect_overrides(document.get("track_edits"))
    prompt = _apply_track_overrides(prompt, overrides)
    prompt = _apply_rigid_transforms(prompt, document.get("rigid_transforms") or ())
    for operation_index, operation in enumerate(operations):
        if operation["kind"] == "mask":
            prompt, residue_ids = _apply_random_mask(
                prompt,
                operation,
            )
            traces[operation_index] = {
                "operation_index": operation_index,
                "kind": "mask",
                "residue_ids": residue_ids,
            }
    prompt = _apply_function_annotations(prompt, document)
    return prompt, tuple(
        traces[index] for index in sorted(traces)
    ), merge_targets


def apply_prompt_recipe(
    *,
    sequence_source: ProteinSequence | None,
    structure_source: ResolvedStructureResidueAxis | None,
    prompt_source: ProteinPrompt | None,
    merge_sources: Sequence[ProteinPrompt],
    document: Mapping[str, Any],
) -> ProteinPrompt:
    """Apply one authoring document through the sole scientific path."""
    prompt, _trace, _merge_targets = _evaluate_prompt_recipe(
        sequence_source=sequence_source,
        structure_source=structure_source,
        prompt_source=prompt_source,
        merge_sources=merge_sources,
        document=document,
    )
    return prompt
