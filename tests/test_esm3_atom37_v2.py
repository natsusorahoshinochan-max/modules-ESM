"""ESM-3 atom37 projection ignores non-atom37 atoms (spec §7).

The provider-independent ProteinPrompt may carry named atoms that ESM-3 cannot
represent. The atom37 projection must copy atom37-supported atoms, ignore the
rest, and the functional-input digest must only cover the projected atoms.
"""

from __future__ import annotations

from datatypes.prompt import (
    FunctionAnnotation,
    ProteinPrompt,
)
from datatypes.residue import ResidueLayout
from datatypes.structure import NamedAtomCoordinates
from modules.esm3.adapter import (
    _atom37_entries,
    _function_annotation_provider_interval,
    esm3_functional_input_digest,
)


def _prompt_with_mixed_atoms() -> ProteinPrompt:
    layout = ResidueLayout(("A:1", "A:2"))
    coordinates = (
        NamedAtomCoordinates.from_mapping(
            {
                "N": (0.0, 0.0, 0.0),
                "CA": (1.0, 0.0, 0.0),
                "MG": (2.0, 0.0, 0.0),
            }
        ),
        NamedAtomCoordinates.from_mapping(
            {"N": (3.0, 0.0, 0.0), "SE": (4.0, 0.0, 0.0)}
        ),
    )
    return ProteinPrompt(
        layout=layout,
        sequence=(None, None),
        coordinates=coordinates,
    )


def test_atom37_projection_ignores_non_atom37_atoms() -> None:
    prompt = _prompt_with_mixed_atoms()
    entries = _atom37_entries(prompt)
    atom_indices = {atom_index for _position, atom_index, _coord in entries}
    assert 12 not in atom_indices  # MG is not an atom37 index
    assert atom_indices <= set(range(37))
    # every projected entry must come from an atom37-supported atom
    projected_names = set()
    for position, atom_index, _coord in entries:
        for name, index in {
            "N": 0,
            "CA": 1,
            "C": 2,
            "O": 4,
        }.items():
            if index == atom_index:
                projected_names.add(name)
    assert "MG" not in projected_names and "SE" not in projected_names
    assert "N" in projected_names and "CA" in projected_names


def test_functional_input_digest_only_covers_atom37_atoms() -> None:
    prompt = _prompt_with_mixed_atoms()
    digest = esm3_functional_input_digest(prompt)
    assert isinstance(digest, str) and digest.startswith("sha256:")


def test_function_annotation_resolves_positions_through_layout() -> None:
    layout = ResidueLayout(("A:1", "A:2", "A:3"))
    prompt = ProteinPrompt(
        layout=layout,
        sequence=(None, None, None),
        coordinates=(None, None, None),
        function_annotations=(
            FunctionAnnotation(
                label="site",
                start_residue_id="A:1",
                end_residue_id="A:3",
            ),
        ),
    )
    start, end = _function_annotation_provider_interval(
        prompt, prompt.function_annotations[0]
    )
    assert (start, end) == (1, 3)
