"""Function-annotation authoring against exact residue layouts."""

from __future__ import annotations

from collections.abc import Mapping

from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotations,
)
from datatypes.residue import ResidueLayout

from .domain import residue_chain


def _interval_positions(
    residue_index: Mapping[str, int],
    start_residue_id: str,
    end_residue_id: str,
    *,
    subject: str,
) -> tuple[int, int]:
    if (
        start_residue_id not in residue_index
        or end_residue_id not in residue_index
    ):
        raise ValueError(
            f"{subject} endpoints do not correspond to the layout"
        )
    start_position = residue_index[start_residue_id]
    end_position = residue_index[end_residue_id]
    if start_position > end_position:
        raise ValueError(f"{subject} interval is not ordered")
    return start_position, end_position


def require_function_annotation_layout(
    annotations: FunctionAnnotations,
    layout: ResidueLayout,
    *,
    overlap_policy: str | None = None,
) -> FunctionAnnotations:
    """Require only the cross-value annotation-to-layout relationship."""
    residue_index = {
        residue_id: index
        for index, residue_id in enumerate(layout.residue_ids)
    }
    for index, annotation in enumerate(annotations.annotations):
        subject = f"function_annotations[{index}]"
        start_position, end_position = _interval_positions(
            residue_index,
            annotation.start_residue_id,
            annotation.end_residue_id,
            subject=subject,
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
    return annotations


def add_function_annotation(
    layout: ResidueLayout,
    existing: FunctionAnnotations | None,
    annotation: Mapping[str, str],
    *,
    overlap_policy: str,
) -> FunctionAnnotations:
    """Add one chain-qualified annotation and canonicalize its ordering."""
    if existing is None:
        current = FunctionAnnotations()
    else:
        current = require_function_annotation_layout(
            existing,
            layout,
            overlap_policy=overlap_policy,
        )
    residue_index = {
        residue_id: index
        for index, residue_id in enumerate(layout.residue_ids)
    }
    start_residue_id = annotation["start_residue_id"]
    end_residue_id = annotation["end_residue_id"]
    chain_id = annotation["chain_id"]
    if (
        residue_chain(start_residue_id) != chain_id
        or residue_chain(end_residue_id) != chain_id
    ):
        raise ValueError(
            "function_annotation endpoints do not correspond to its chain"
        )
    start_position, end_position = _interval_positions(
        residue_index,
        start_residue_id,
        end_residue_id,
        subject="function_annotation",
    )
    candidate = FunctionAnnotation(
        label=annotation["label"],
        start=start_position + 1,
        end=end_position + 1,
        chain_id=chain_id,
        start_residue_id=start_residue_id,
        end_residue_id=end_residue_id,
        overlap_policy=overlap_policy,
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
    return appended
