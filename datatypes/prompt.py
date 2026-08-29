"""Provider-independent multi-track protein prompt values."""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from typing import Any, Optional

from datatypes.i_json import FrozenList, freeze_i_json
from datatypes.residue import ResidueLayout, ResidueTrack, residue_identity_chain


def _ordered_list(value: object, *, field_name: str) -> FrozenList:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return FrozenList(value)


def _freeze_annotation(value: Any) -> Any:
    parameters = getattr(type(value), "__dataclass_params__", None)
    if is_dataclass(value) and parameters is not None and parameters.frozen:
        return value
    return freeze_i_json(value)


@dataclass(frozen=True, slots=True)
class FunctionAnnotations:
    """Named function annotations as residue ranges."""

    annotations: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "annotations",
            FrozenList(
                _freeze_annotation(item)
                for item in _ordered_list(
                    self.annotations,
                    field_name="annotations",
                )
            ),
        )

    def __len__(self) -> int:
        return len(self.annotations)


@dataclass(frozen=True, slots=True)
class ProteinPrompt:
    """Multi-track protein prompt for ESM3 conditioning.

    All per-residue tracks must have length equal to the target layout length.
    Sequence and structure use one explicit nullable value per residue. A
    whole-track mask is represented by an all-null track, not by absence.
    """

    target_layout: ResidueLayout
    sequence_track: ResidueTrack
    structure_track: ResidueTrack
    secondary_structure_track: Optional[ResidueTrack] = None
    sasa_track: Optional[ResidueTrack] = None
    function_annotations: FunctionAnnotations = field(default_factory=FunctionAnnotations)

    @property
    def num_residues(self) -> int:
        return self.target_layout.length

@dataclass(frozen=True, slots=True)
class FunctionAnnotation:
    """One canonical one-based inclusive interval with residue provenance."""

    label: str
    start: int
    end: int
    chain_id: str
    start_residue_id: str
    end_residue_id: str

def validate_canonical_function_annotations(
    value: object,
) -> tuple[FunctionAnnotation, ...]:
    """Validate canonical ordering and residue provenance shape."""
    if type(value) is not FunctionAnnotations:
        raise ValueError("function_annotations must be FunctionAnnotations")
    previous_key: tuple[object, ...] | None = None
    annotations: list[FunctionAnnotation] = []
    for index, annotation in enumerate(value.annotations):
        subject = f"function_annotations[{index}]"
        if type(annotation) is not FunctionAnnotation:
            raise ValueError(f"{subject} must be a FunctionAnnotation")
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
        if (
            type(annotation.chain_id) is not str
            or start_chain != annotation.chain_id
            or end_chain != annotation.chain_id
        ):
            raise ValueError(
                f"{subject} chain-qualified provenance is invalid"
            )
        if (
            type(annotation.start) is not int
            or type(annotation.end) is not int
            or annotation.start < 1
            or annotation.end < annotation.start
        ):
            raise ValueError(
                f"{subject} must use an ordered one-based inclusive interval"
            )
        key = (
            annotation.start,
            annotation.end,
            annotation.label,
            annotation.chain_id,
            annotation.start_residue_id,
            annotation.end_residue_id,
        )
        if previous_key is not None and key <= previous_key:
            raise ValueError(
                "function_annotations must use unique canonical ordering"
            )
        previous_key = key
        annotations.append(annotation)
    return tuple(annotations)
