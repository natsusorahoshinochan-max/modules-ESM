"""Shared element admission and its complete scientific value interfaces."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

import pytest

from core.catalog.errors import PortValueError
from datatypes.candidate import CandidateDataReference
from datatypes.prompt import ProteinPrompt
from datatypes.residue import CandidateResidueTrack, ResidueLayout, ResidueTrack
from datatypes.structure import NamedAtomCoordinates
from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE
from modules.prompt_authoring.prompts import validate_protein_prompt
from modules.residue_data.elements import (
    validate_coordinate_elements,
    validate_sasa_elements,
    validate_secondary_structure_elements,
    validate_sequence_elements,
)
from modules.residue_data.port_types import RESIDUE_CONDITION_PORT_TYPES
from modules.structure_annotation.port_types import STRUCTURE_ANNOTATION_PORT_TYPES


class ElementValidator(Protocol):
    def __call__(self, values: Sequence[object], *, subject: str) -> None: ...


@pytest.mark.parametrize(
    ("validator", "values"),
    [
        (validate_sequence_elements, tuple("ACDEFGHIKLMNPQRSTVWYBXZJUO")),
        (validate_secondary_structure_elements, tuple("HBEGITSC")),
        (validate_sasa_elements, (0.0, -0.0, 12.5, 1e100)),
        (
            validate_coordinate_elements,
            (NamedAtomCoordinates.from_mapping({"CUSTOM": (1.0, 2.0, 3.0)}),),
        ),
    ],
)
def test_element_admission_preserves_canonical_values_and_nulls(
    validator: ElementValidator, values: tuple[object, ...],
) -> None:
    elements = [None, *values, None]
    original = tuple(elements)
    assert validator(elements, subject="track") is None
    assert tuple(elements) == original
    assert all(after is before for after, before in zip(elements, original, strict=True))
    assert validator((None, None), subject="track") is None
    # Element admission does not own Layout non-emptiness or track length.
    assert validator((), subject="track") is None


@pytest.mark.parametrize("invalid", ["", "AC", "a", "-", "_", "*", 1, True])
def test_sequence_elements_require_one_canonical_code(invalid: object) -> None:
    with pytest.raises(ValueError, match=r"sequence\[1\].*amino-acid"):
        validate_sequence_elements((None, invalid), subject="sequence")


@pytest.mark.parametrize("invalid", ["", "HE", "h", "-", "_", "P", 1, True])
def test_ss8_elements_do_not_normalize_source_tokens(invalid: object) -> None:
    with pytest.raises(ValueError, match=r"secondary\[1\].*canonical SS8"):
        validate_secondary_structure_elements((None, invalid), subject="secondary")


@pytest.mark.parametrize("invalid", [{"CA": (1.0, 2.0, 3.0)}, (1.0, 2.0, 3.0), "CA"])
def test_coordinate_elements_require_named_atom_values(invalid: object) -> None:
    with pytest.raises(ValueError, match=r"coordinates\[1\].*NamedAtomCoordinates"):
        validate_coordinate_elements((None, invalid), subject="coordinates")


@pytest.mark.parametrize(
    "invalid", [0, 1, True, False, -0.1, float("nan"), float("inf"), -float("inf"), "1.0"],
)
def test_sasa_elements_require_finite_nonnegative_floats(invalid: object) -> None:
    with pytest.raises(ValueError, match=r"sasa\[1\].*square angstroms"):
        validate_sasa_elements((None, invalid), subject="sasa")


def test_element_contracts_require_exact_canonical_types() -> None:
    class Text(str):
        pass

    class Area(float):
        pass

    class Coordinates(NamedAtomCoordinates):
        pass

    cases: tuple[tuple[ElementValidator, object], ...] = (
        (validate_sequence_elements, Text("A")),
        (validate_secondary_structure_elements, Text("H")),
        (validate_sasa_elements, Area(1.0)),
        (validate_coordinate_elements, Coordinates(())),
    )
    for validator, value in cases:
        with pytest.raises(ValueError, match=r"track\[0\]"):
            validator((value,), subject="track")


@pytest.mark.parametrize(
    ("kind", "valid", "invalid", "diagnostic"),
    [
        ("sequence", "U", "?", "amino-acid"),
        (
            "coordinates",
            NamedAtomCoordinates.from_mapping({"CUSTOM": (1.0, 2.0, 3.0)}),
            "CA",
            "NamedAtomCoordinates",
        ),
        ("secondary_structure", "C", "P", "canonical SS8"),
        ("sasa", 0.0, 0, "square angstroms"),
    ],
)
def test_scientific_value_owners_admit_shared_elements(
    kind: str, valid: object, invalid: object, diagnostic: str,
) -> None:
    layout = ResidueLayout(("A:2", "B:7"))
    prompt = replace(
        ProteinPrompt(layout, (None, None), (None, None)),
        **{kind: (None, valid)},
    )
    assert validate_protein_prompt(prompt) is prompt
    assert PROTEIN_PROMPT_PORT_TYPE.decode(PROTEIN_PROMPT_PORT_TYPE.encode(prompt)) == prompt
    invalid_prompt = replace(prompt, **{kind: (None, invalid)})
    with pytest.raises(ValueError, match=rf"\[1\].*{diagnostic}"):
        validate_protein_prompt(invalid_prompt)
    with pytest.raises(PortValueError, match=rf"\[1\].*{diagnostic}"):
        PROTEIN_PROMPT_PORT_TYPE.encode(invalid_prompt)

    conditioning = next(
        port for port in RESIDUE_CONDITION_PORT_TYPES
        if port.type_id == f"residue.condition.{kind}"
    )
    track = ResidueTrack(layout, (None, valid))
    assert conditioning.decode(conditioning.encode(track)) == track
    with pytest.raises(PortValueError, match=rf"values\[1\].*{diagnostic}"):
        conditioning.encode(ResidueTrack(layout, (None, invalid)))

    if kind in ("secondary_structure", "sasa"):
        observed = next(
            port for port in STRUCTURE_ANNOTATION_PORT_TYPES
            if port.type_id == f"structure_annotation.{kind}.observed"
        )
        subject = CandidateDataReference("structure", "protein.structure", "sha256:" + "a" * 64)
        annotation = CandidateResidueTrack(subject, track)
        decoded = observed.decode(observed.encode(annotation))
        assert decoded == annotation
        assert decoded.subject == subject
        if kind == "sasa":
            # Canonical JSON encodes 0.0 as 0; the nominal decoder restores float.
            assert type(decoded.track.values[1]) is float
        with pytest.raises(PortValueError, match=rf"values\[1\].*{diagnostic}"):
            observed.encode(CandidateResidueTrack(subject, ResidueTrack(layout, (None, invalid))))
