"""Canonical v2 function-annotation scientific values."""

from __future__ import annotations

from dataclasses import dataclass

from datatypes.protein import (
    FunctionAnnotations,
    residue_identity_chain,
)


@dataclass(frozen=True, slots=True)
class FunctionAnnotation:
    """One canonical one-based inclusive interval with residue provenance."""

    label: str
    start: int
    end: int
    chain_id: str
    start_residue_id: str
    end_residue_id: str
    overlap_policy: str

    def to_record(self) -> dict[str, object]:
        """Return the closed canonical wire record."""
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "chain_id": self.chain_id,
            "start_residue_id": self.start_residue_id,
            "end_residue_id": self.end_residue_id,
            "overlap_policy": self.overlap_policy,
        }


def validate_canonical_function_annotations(
    value: object,
) -> tuple[FunctionAnnotation, ...]:
    """Validate canonical ordering, provenance shape, and overlap semantics."""
    if type(value) is not FunctionAnnotations:
        raise ValueError("function_annotations must be FunctionAnnotations")
    policy: str | None = None
    previous_key: tuple[object, ...] | None = None
    previous_end = 0
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
        if (
            type(annotation.overlap_policy) is not str
            or annotation.overlap_policy not in {"allow", "reject"}
        ):
            raise ValueError(f"{subject}.overlap_policy is invalid")
        if policy is None:
            policy = annotation.overlap_policy
        elif annotation.overlap_policy != policy:
            raise ValueError(
                "function_annotations cannot mix overlap policies"
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
        if policy == "reject" and annotation.start <= previous_end:
            raise ValueError(
                "function_annotations overlap under the reject policy"
            )
        previous_key = key
        previous_end = max(previous_end, annotation.end)
        annotations.append(annotation)
    return tuple(annotations)
