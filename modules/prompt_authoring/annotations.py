"""Function-annotation replacement against one authoritative layout."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from datatypes.prompt import FunctionAnnotation, validate_canonical_function_annotations
from datatypes.residue import ResidueLayout


def replace_function_annotations(
    layout: ResidueLayout,
    annotations: Sequence[Mapping[str, str]],
) -> tuple[FunctionAnnotation, ...]:
    """Order a complete collection without altering or deduplicating intervals."""
    residue_index = {residue_id: index for index, residue_id in enumerate(layout.residue_ids)}
    values = tuple(FunctionAnnotation(**annotation) for annotation in annotations)
    try:
        ordered = tuple(sorted(values, key=lambda item: (
            residue_index[item.start_residue_id],
            residue_index[item.end_residue_id],
            item.label,
        )))
    except KeyError as error:
        raise ValueError("function annotation endpoints do not correspond to the layout") from error
    return validate_canonical_function_annotations(layout, ordered)
