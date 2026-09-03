"""Provider-independent closed multi-track protein prompt values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from datatypes.i_json import FrozenList
from datatypes.residue import ResidueLayout, residue_identity_chain
from datatypes.structure import NamedAtomCoordinates


@dataclass(frozen=True, slots=True)
class FunctionAnnotation:
    """One identity-addressed function annotation interval.

    The containing ProteinPrompt layout is the only position owner. Provider
    positions are resolved from residue identities by each Adapter.
    """

    label: str
    start_residue_id: str
    end_residue_id: str


@dataclass(frozen=True, slots=True)
class ProteinPrompt:
    """Residue-aligned multi-track conditioning aggregate.

    The aggregate owns its ``ResidueLayout`` exactly once. Sequence and
    coordinates are always present (all-null allowed). Secondary structure
    and SASA may be whole-track absent (``None``), which is distinct from a
    present all-null track.
    """

    layout: ResidueLayout
    sequence: tuple[Optional[str], ...]
    coordinates: tuple[Optional[NamedAtomCoordinates], ...]
    secondary_structure: Optional[tuple[Optional[str], ...]] = None
    sasa: Optional[tuple[Optional[float], ...]] = None
    function_annotations: tuple[FunctionAnnotation, ...] = ()

    def __post_init__(self) -> None:
        if type(self.layout) is not ResidueLayout:
            raise ValueError("ProteinPrompt layout must be a ResidueLayout")
        length = self.layout.length
        object.__setattr__(
            self,
            "sequence",
            FrozenList(self.sequence),
        )
        object.__setattr__(
            self,
            "coordinates",
            FrozenList(self.coordinates),
        )
        object.__setattr__(
            self,
            "function_annotations",
            FrozenList(self.function_annotations),
        )
        if len(self.sequence) != length:
            raise ValueError(
                "ProteinPrompt sequence length "
                f"{len(self.sequence)} != layout length {length}"
            )
        if len(self.coordinates) != length:
            raise ValueError(
                "ProteinPrompt coordinates length "
                f"{len(self.coordinates)} != layout length {length}"
            )
        if self.secondary_structure is not None:
            if len(self.secondary_structure) != length:
                raise ValueError(
                    "ProteinPrompt secondary_structure length "
                    f"{len(self.secondary_structure)} != layout length {length}"
                )
            object.__setattr__(
                self,
                "secondary_structure",
                FrozenList(self.secondary_structure),
            )
        if self.sasa is not None:
            if len(self.sasa) != length:
                raise ValueError(
                    "ProteinPrompt sasa length "
                    f"{len(self.sasa)} != layout length {length}"
                )
            object.__setattr__(
                self,
                "sasa",
                FrozenList(self.sasa),
            )

    @property
    def num_residues(self) -> int:
        return self.layout.length


@dataclass(frozen=True, slots=True)
class FunctionAnnotationTrack:
    """Identity-addressed function annotations bound to one exact layout.

    This is the self-describing carrier for annotations that travel without
    a ProteinPrompt: it owns the authoritative layout the interval
    identities address.
    """

    layout: ResidueLayout
    annotations: tuple[FunctionAnnotation, ...]

    def __post_init__(self) -> None:
        if type(self.layout) is not ResidueLayout:
            raise ValueError(
                "FunctionAnnotationTrack layout must be a ResidueLayout"
            )
        object.__setattr__(
            self,
            "annotations",
            FrozenList(self.annotations),
        )
        validate_canonical_function_annotations(self.annotations)
        addressed = {
            residue_id
            for annotation in self.annotations
            for residue_id in (
                annotation.start_residue_id,
                annotation.end_residue_id,
            )
        }
        unknown = addressed - set(self.layout.residue_ids)
        if unknown:
            raise ValueError(
                "FunctionAnnotationTrack annotations address residue "
                "identities outside the layout"
            )


def validate_canonical_function_annotations(
    value: object,
) -> tuple[FunctionAnnotation, ...]:
    """Validate canonical ordering and closed identity-addressed shape."""
    if not isinstance(value, (tuple, FrozenList)) or not all(
        type(annotation) is FunctionAnnotation for annotation in value
    ):
        raise ValueError(
            "function_annotations must be a FunctionAnnotation tuple"
        )
    previous_key: tuple[str, str, str] | None = None
    for index, annotation in enumerate(value):
        subject = f"function_annotations[{index}]"
        if (
            type(annotation.label) is not str
            or not annotation.label
            or annotation.label != annotation.label.strip()
            or len(annotation.label) > 256
            or any(ord(character) < 32 for character in annotation.label)
        ):
            raise ValueError(f"{subject}.label is invalid")
        start_chain = residue_identity_chain(
            annotation.start_residue_id,
            subject=f"{subject}.start_residue_id",
        )
        end_chain = residue_identity_chain(
            annotation.end_residue_id,
            subject=f"{subject}.end_residue_id",
        )
        if start_chain != end_chain:
            raise ValueError(
                f"{subject} must address one interval within one chain"
            )
        key = (
            annotation.start_residue_id,
            annotation.end_residue_id,
            annotation.label,
        )
        if previous_key is not None and key <= previous_key:
            raise ValueError(
                "function_annotations must use unique canonical ordering"
            )
        previous_key = key
    return tuple(value)
