"""Function-annotation authoring against exact residue layouts."""

from __future__ import annotations

from collections.abc import Mapping

from datatypes import (
    FunctionAnnotation,
    FunctionAnnotations,
    ResidueLayout,
    validate_canonical_function_annotations,
)

from .domain import residue_chain, validate_layout


def validate_function_annotations(
    value: object,
    layout: object,
    *,
    overlap_policy: str | None = None,
) -> FunctionAnnotations:
    """Validate canonical annotations against one effective residue layout."""
    target = validate_layout(layout, subject="annotation layout")
    annotations = validate_canonical_function_annotations(value)
    if overlap_policy is not None and overlap_policy not in {"allow", "reject"}:
        raise ValueError("overlap_policy must be allow or reject")
    residue_ids = tuple(target.residue_ids or ())
    residue_index = {
        residue_id: index for index, residue_id in enumerate(residue_ids)
    }
    for index, annotation in enumerate(annotations):
        subject = f"function_annotations[{index}]"
        if (
            annotation.start_residue_id not in residue_index
            or annotation.end_residue_id not in residue_index
            or residue_chain(annotation.start_residue_id)
            != annotation.chain_id
            or residue_chain(annotation.end_residue_id)
            != annotation.chain_id
        ):
            raise ValueError(
                f"{subject} endpoints do not correspond to one layout chain"
            )
        start_position = residue_index[annotation.start_residue_id]
        end_position = residue_index[annotation.end_residue_id]
        if start_position > end_position or any(
            residue_chain(residue_ids[position]) != annotation.chain_id
            for position in range(start_position, end_position + 1)
        ):
            raise ValueError(
                f"{subject} interval is not ordered within one chain"
            )
        if (
            annotation.start != start_position + 1
            or annotation.end != end_position + 1
        ):
            raise ValueError(
                f"{subject} interval contradicts residue provenance"
            )
        if (
            overlap_policy is not None
            and annotation.overlap_policy != overlap_policy
        ):
            raise ValueError(
                "function_annotations overlap policy does not match"
            )
    assert isinstance(value, FunctionAnnotations)
    return value


def add_function_annotation(
    layout: object,
    existing: object | None,
    annotation: object,
    *,
    overlap_policy: object,
) -> FunctionAnnotations:
    """Add one chain-qualified annotation and canonicalize its ordering."""
    target = validate_layout(layout, subject="annotation layout")
    if overlap_policy not in {"allow", "reject"}:
        raise ValueError("overlap_policy must be allow or reject")
    if existing is None:
        current = FunctionAnnotations()
    else:
        current = validate_function_annotations(
            existing,
            target,
            overlap_policy=overlap_policy,
        )
    if not isinstance(annotation, Mapping) or set(annotation) != {
        "label",
        "chain_id",
        "start_residue_id",
        "end_residue_id",
    }:
        raise ValueError(
            "annotation must contain only label, chain_id, and residue endpoints"
        )
    residue_ids = tuple(target.residue_ids or ())
    residue_index = {
        residue_id: index for index, residue_id in enumerate(residue_ids)
    }
    start_residue_id = annotation["start_residue_id"]
    end_residue_id = annotation["end_residue_id"]
    candidate = FunctionAnnotation(
        label=annotation["label"],
        start=(
            residue_index[start_residue_id] + 1
            if isinstance(start_residue_id, str)
            and start_residue_id in residue_index
            else -1
        ),
        end=(
            residue_index[end_residue_id] + 1
            if isinstance(end_residue_id, str)
            and end_residue_id in residue_index
            else -1
        ),
        chain_id=annotation["chain_id"],
        start_residue_id=start_residue_id,
        end_residue_id=end_residue_id,
        overlap_policy=overlap_policy,
    )
    validate_canonical_function_annotations(
        FunctionAnnotations([candidate])
    )
    appended = FunctionAnnotations(
        sorted(
            [*current.annotations, candidate],
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
    return validate_function_annotations(
        appended,
        target,
        overlap_policy=overlap_policy,
    )
