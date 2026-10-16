"""Authoring uses the ESM3 owners' exact read-only scientific interpretation."""

from __future__ import annotations

from dataclasses import replace
import struct

from datatypes.prompt import FunctionAnnotation, ProteinPrompt
from datatypes.residue import ResidueLayout
from datatypes.structure import NamedAtomCoordinates
from modules.esm3.adapter import describe_conditioning
from modules.esm3.implementation import describe_generation_compatibility


def test_effective_conditioning_exposes_atom37_rounding_without_changing_prompt() -> None:
    prompt = ProteinPrompt(
        layout=ResidueLayout(("A:10", "A:12A")),
        sequence=("A", None),
        coordinates=(NamedAtomCoordinates.from_mapping({"CA": (1.234567891, 2., 3.), "QX": (8., 9., 10.)}), None),
        secondary_structure=(None, "H"),
        sasa=(None, 12.5),
        function_annotations=(FunctionAnnotation("site", "A:10", "A:12A"),),
    )
    view = describe_conditioning(prompt)
    assert view["status"] == "compatible"
    effective = view["effective_input"]
    assert effective["sequence"] == "A_"
    assert effective["secondary_structure"] == "_H"
    assert effective["sasa"] == [None, 12.5]
    assert effective["function_annotations"] == [{"label": "site", "start": 1, "end": 2}]
    coordinates = effective["coordinates"]
    assert coordinates["shape"] == [2, 37, 3]
    assert coordinates["dtype"] == "float32"
    assert coordinates["entries"][0]["residue_id"] == "A:10"
    assert coordinates["entries"][0]["atom_name"] == "CA"
    assert coordinates["entries"][0]["atom_index"] == 1
    assert coordinates["entries"][0]["coordinates"][0] == struct.unpack("!f", struct.pack("!f", 1.234567891))[0]
    assert coordinates["entries"][0]["float32_bits"][0] == "3f9e0652"
    assert coordinates["omitted_named_atoms"] == [{"residue_id": "A:10", "atom_name": "QX"}]
    assert len(prompt.coordinates[0].atoms) == 2
    assert prompt.coordinates[0].atoms[0][1][0] == 1.234567891
    assert describe_generation_compatibility(prompt) == {
        "generate_sequence": {"compatible": True, "reason": None},
        "generate_structure": {"compatible": False, "reason": "structure generation requires a complete assigned sequence"},
        "generate_paired": {"compatible": True, "reason": None},
    }


def test_effective_conditioning_distinguishes_absent_optional_tracks_and_all_masks() -> None:
    prompt = ProteinPrompt(ResidueLayout(("A:1",)), (None,), (None,))
    absent = describe_conditioning(prompt)["effective_input"]
    masked = describe_conditioning(replace(prompt, secondary_structure=(None,), sasa=(None,)))["effective_input"]
    assert absent["secondary_structure"] is None
    assert absent["sasa"] is None
    assert masked["secondary_structure"] == "_"
    assert masked["sasa"] == [None]
    assert absent["functional_input_digest"] != masked["functional_input_digest"]
    assert absent["coordinates"]["present"] is False
    assert absent["coordinates"]["shape"] is None


def test_multichain_is_a_model_compatibility_outcome_not_a_prompt_error() -> None:
    prompt = ProteinPrompt(ResidueLayout(("A:1", "B:1")), ("A", "C"), (None, None))
    view = describe_conditioning(prompt)
    assert view == {"status": "unsupported", "reason": "The ESM SDK cannot preserve multi-chain aligned tracks", "effective_input": None}
    modes = describe_generation_compatibility(prompt)
    assert modes["generate_structure"]["compatible"] is True
    assert modes["generate_sequence"]["compatible"] is False
