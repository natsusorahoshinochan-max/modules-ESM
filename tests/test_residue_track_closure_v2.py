"""ResidueTrack / ResidueLayout closure, reindex, and ProteinPrompt identity.

Mirrors spec §4.1-§4.4 and §5: layout/value length closure, identity-addressed
reindex, the absent-vs-present-all-null distinction, and FunctionAnnotation
identity addressing resolved through the layout.
"""

from __future__ import annotations

from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotationTrack,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
    reindex_residue_track,
)
from datatypes.structure import NamedAtomCoordinates


def test_residue_track_length_must_match_layout() -> None:
    layout = ResidueLayout(("A:1", "A:2", "A:3"))
    track = ResidueTrack(layout, ("M", None, "K"))
    assert track.layout is layout
    assert len(track) == 3
    assert track.values == ("M", None, "K")


def test_residue_track_rejects_length_mismatch() -> None:
    layout = ResidueLayout(("A:1", "A:2"))
    try:
        ResidueTrack(layout, ("M", None, "K"))
    except ValueError:
        pass
    else:
        raise AssertionError("length mismatch must raise ValueError")


def test_reindex_preserves_shared_identities_and_fills_missing() -> None:
    source = ResidueLayout(("A:1", "A:2", "A:3"))
    target = ResidueLayout(("A:1", "A:3", "B:1"))
    track = ResidueTrack(source, ("M", "G", "K"))
    reindexed = reindex_residue_track(track, target)
    assert reindexed.layout == target
    assert reindexed.values == ("M", "K", None)


def test_protein_prompt_absent_ss8_differs_from_present_all_null() -> None:
    layout = ResidueLayout(("A:1", "A:2"))
    base = dict(
        layout=layout,
        sequence=("M", "K"),
        coordinates=(None, None),
    )
    absent = ProteinPrompt(**base, secondary_structure=None)
    present_all_null = ProteinPrompt(
        **base, secondary_structure=(None, None)
    )
    assert absent.secondary_structure is None
    assert present_all_null.secondary_structure == (None, None)
    assert absent.secondary_structure != present_all_null.secondary_structure


def test_protein_prompt_absent_sasa_differs_from_present_all_null() -> None:
    layout = ResidueLayout(("A:1", "A:2"))
    base = dict(
        layout=layout,
        sequence=("M", "K"),
        coordinates=(None, None),
    )
    absent = ProteinPrompt(**base, sasa=None)
    present_all_null = ProteinPrompt(**base, sasa=(None, None))
    assert absent.sasa is None
    assert present_all_null.sasa == (None, None)
    assert absent.sasa is not present_all_null.sasa


def test_function_annotation_addresses_layout_identities() -> None:
    layout = ResidueLayout(("A:1", "A:2", "A:3"))
    prompt = ProteinPrompt(
        layout=layout,
        sequence=("M", "K", "G"),
        coordinates=(None, None, None),
        function_annotations=(
            FunctionAnnotation(
                label="binding_site",
                start_residue_id="A:1",
                end_residue_id="A:2",
            ),
        ),
    )
    annotation = prompt.function_annotations[0]
    assert annotation.start_residue_id == "A:1"
    assert annotation.end_residue_id == "A:2"


def test_function_annotation_track_rejects_out_of_layout_identity() -> None:
    layout = ResidueLayout(("A:1", "A:2"))
    try:
        FunctionAnnotationTrack(
            layout,
            (
                FunctionAnnotation(
                    label="bad",
                    start_residue_id="A:9",
                    end_residue_id="A:2",
                ),
            ),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-layout annotation must raise ValueError")


def test_named_atom_coordinates_expose_atom_names_and_lookup() -> None:
    coords = NamedAtomCoordinates.from_mapping(
        {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)}
    )
    assert coords.atom_names == ("CA", "N")
    assert coords.coordinate_for("N") == (0.0, 0.0, 0.0)


def test_protein_prompt_codec_normalizes_only_sasa_json_integers() -> None:
    from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE

    prompt = ProteinPrompt(
        layout=ResidueLayout(("A:1", "A:2")),
        sequence=("A", "C"),
        coordinates=(None, None),
        sasa=(0.0, 12.0),
    )
    decoded = PROTEIN_PROMPT_PORT_TYPE.decode(PROTEIN_PROMPT_PORT_TYPE.encode(prompt))
    assert decoded == prompt
    assert decoded.sasa is not None
    assert all(type(value) is float for value in decoded.sasa)
