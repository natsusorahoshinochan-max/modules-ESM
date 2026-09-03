"""Function-annotation authoring against exact residue layouts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from datatypes.prompt import FunctionAnnotation
from datatypes.residue import ResidueLayout


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
    annotations: Sequence[FunctionAnnotation],
    layout: ResidueLayout,
) -> tuple[FunctionAnnotation, ...]:
    """Require only the cross-value annotation-to-layout relationship."""
    residue_index = {
        residue_id: index
        for index, residue_id in enumerate(layout.residue_ids)
    }
    for index, annotation in enumerate(annotations):
        _interval_positions(
            residue_index,
            annotation.start_residue_id,
            annotation.end_residue_id,
            subject=f"function_annotations[{index}]",
        )
    return tuple(annotations)


def add_function_annotation(
    layout: ResidueLayout,
    existing: Sequence[FunctionAnnotation] | None,
    annotation: Mapping[str, str],
    *,
    overlap_policy: str,
) -> tuple[FunctionAnnotation, ...]:
    """Add one identity-addressed annotation and canonicalize ordering."""
    residue_index = {
        residue_id: index
        for index, residue_id in enumerate(layout.residue_ids)
    }
    start_residue_id = annotation["start_residue_id"]
    end_residue_id = annotation["end_residue_id"]
    start_position, end_position = _interval_positions(
        residue_index,
        start_residue_id,
        end_residue_id,
        subject="function_annotation",
    )
    candidate = FunctionAnnotation(
        label=annotation["label"],
        start_residue_id=start_residue_id,
        end_residue_id=end_residue_id,
    )
    ordered = sorted(
        [*(existing if existing is not None else ()), candidate],
        key=lambda item: (
            residue_index[item.start_residue_id],
            residue_index[item.end_residue_id],
            item.label,
        ),
    )
    if overlap_policy == "reject":
        previous_end_position = -1
        for item in ordered:
            item_start = residue_index[item.start_residue_id]
            item_end = residue_index[item.end_residue_id]
            if item_start <= previous_end_position:
                raise ValueError(
                    "function annotations overlap under the reject policy"
                )
            previous_end_position = item_end
    return tuple(ordered)


def replace_function_annotations(
    layout: ResidueLayout,
    annotations: Sequence[Mapping[str, str]],
    *,
    overlap_policy: str,
) -> tuple[FunctionAnnotation, ...]:
    """Materialize one complete final annotation collection."""
    result: tuple[FunctionAnnotation, ...] = ()
    for annotation in annotations:
        result = add_function_annotation(
            layout,
            result,
            annotation,
            overlap_policy="allow",
        )
    if overlap_policy == "reject":
        residue_index = {
            residue_id: index
            for index, residue_id in enumerate(layout.residue_ids)
        }
        previous_end_position = -1
        for item in result:
            item_start = residue_index[item.start_residue_id]
            item_end = residue_index[item.end_residue_id]
            if item_start <= previous_end_position:
                raise ValueError(
                    "function annotations overlap under the reject policy"
                )
            previous_end_position = item_end
    return result
