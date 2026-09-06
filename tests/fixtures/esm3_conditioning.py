"""Conditioning values for ESM-3 translation and call-randomness contracts."""

from dataclasses import replace

from datatypes.prompt import FunctionAnnotation, ProteinPrompt
from datatypes.residue import ResidueLayout
from datatypes.structure import NamedAtomCoordinates


def conditioning_prompt(case: str) -> ProteinPrompt:
    """Vary one Provider-visible value or Provider-invisible provenance."""
    masked = ProteinPrompt(
        layout=ResidueLayout(("A:1", "A:2", "A:3")),
        sequence=(None, "C", "D"),
        coordinates=(None, None, None),
    )
    atoms = {"N": (0.1, -0.0, 1.00000006), "CA": (4.0, 5.0, 6.0)}
    rich = replace(
        masked,
        coordinates=(NamedAtomCoordinates.from_mapping(atoms), None, None),
        secondary_structure=("H", None, "C"),
        sasa=(0.1, None, 17.25),
        function_annotations=(
            FunctionAnnotation("binding site", "A:1", "A:2"),
            FunctionAnnotation("active site", "A:2", "A:3"),
        ),
    )
    if case == "masked":
        return masked
    if case == "sequence_changed":
        return replace(masked, sequence=(None, "C", "E"))
    if case == "null_ss8":
        return replace(masked, secondary_structure=(None, None, None))
    if case == "null_sasa":
        return replace(masked, sasa=(None, None, None))
    if case == "unsupported_coordinates":
        return replace(masked, coordinates=(
            NamedAtomCoordinates.from_mapping({"MG": (1.0, 2.0, 3.0)}),
            None,
            None,
        ))
    if case == "rich":
        return rich
    if case == "renamed":
        return replace(
            rich,
            layout=ResidueLayout(("Q:-2", "Q:7A", "Q:12")),
            function_annotations=(
                FunctionAnnotation("binding site", "Q:-2", "Q:7A"),
                FunctionAnnotation("active site", "Q:7A", "Q:12"),
            ),
        )
    if case == "invisible_atoms":
        atoms["MG"] = (9.0, 8.0, 7.0)
    elif case == "rounded_coordinates":
        atoms["N"] = (0.100000001, -0.0, 1.00000006)
    elif case == "positive_zero":
        atoms["N"] = (0.1, 0.0, 1.00000006)
    elif case == "coordinates_absent":
        return replace(rich, coordinates=(None, None, None))
    elif case == "sasa_precision":
        return replace(rich, sasa=(0.10000000000000002, None, 17.25))
    elif case == "ss8_changed":
        return replace(rich, secondary_structure=("E", None, "C"))
    elif case == "annotation_label":
        return replace(rich, function_annotations=(
            FunctionAnnotation("other site", "A:1", "A:2"),
            rich.function_annotations[1],
        ))
    elif case == "annotation_interval":
        return replace(rich, function_annotations=(
            FunctionAnnotation("binding site", "A:1", "A:1"),
            rich.function_annotations[1],
        ))
    else:
        raise ValueError(f"Unknown conditioning case: {case}")
    return replace(rich, coordinates=(
        NamedAtomCoordinates.from_mapping(atoms), None, None,
    ))
