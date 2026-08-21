"""Focused scientific contracts for the resolved structure residue axis."""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

import pytest

from core.catalog.port_contract import (
    PortValueError,
)
from datatypes.structure import ProteinStructure
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from modules.structure_transform.residue_axis import resolve_residue_axis
from modules.structure_transform.port_types import RESOLVED_AXIS_PORT_TYPE
from tests.fixtures.structure_transform_sources.package import _FIXTURES


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _polymer_declaration(
    *,
    record: str,
    component_id: str,
    chain_id: str,
    residue_number: int,
    parent_name: str,
) -> str:
    fields = [" "] * 80
    fields[0:6] = record
    fields[7:11] = "TEST"
    fields[12:15] = component_id
    fields[16] = chain_id
    fields[18:22] = f"{residue_number:4d}"
    fields[24:27] = parent_name
    return "".join(fields)


def _seqres_line(
    chain_id: str,
    components: tuple[str, ...],
) -> str:
    return (
        f"SEQRES {1:3d} {chain_id} {len(components):4d}  "
        + " ".join(components)
    ).ljust(80)


def _mixed_mse_csh_structure() -> tuple[ProteinStructure, str, str]:
    mse_fixture = _FIXTURES["mse_ligand_water"]().splitlines()
    polymer_coordinates = [
        line
        for line in mse_fixture
        if line.startswith(("ATOM  ", "HETATM"))
        and line[21] == "A"
    ]
    csh_coordinates = []
    for line in _FIXTURES["csh"]().splitlines():
        if not line.startswith("HETATM"):
            continue
        fields = list(line)
        fields[22:26] = f"{5:4d}"
        csh_coordinates.append("".join(fields))

    mse_modres = _polymer_declaration(
        record="MODRES",
        component_id="MSE",
        chain_id="A",
        residue_number=2,
        parent_name="MET",
    )
    csh_modres = _polymer_declaration(
        record="MODRES",
        component_id="CSH",
        chain_id="A",
        residue_number=5,
        parent_name="HIS",
    )
    untouched_seqres = _seqres_line("B", ("GLY",))
    return (
        ProteinStructure(
            "\n".join(
                (
                    _seqres_line("A", ("ALA", "MSE", "GLY", "CSH")),
                    untouched_seqres,
                    mse_modres,
                    csh_modres,
                    *polymer_coordinates,
                    "TER",
                    *csh_coordinates,
                    "TER",
                    "END",
                    "",
                )
            )
        ),
        mse_modres,
        untouched_seqres,
    )


def _signed_residue_structure(insertion_code: str) -> ProteinStructure:
    lines = []
    for serial, atom_name in enumerate(("N", "CA", "C", "O"), start=1):
        lines.append(
            f"ATOM  {serial:5d} {atom_name:^4} ALA A{-3:4d}"
            f"{insertion_code or ' '}   "
            f"{float(serial):8.3f}{2.0:8.3f}{3.0:8.3f}"
            f"{1.0:6.2f}{20.0:6.2f}          {atom_name[0]:>2}  "
        )
    return ProteinStructure("\n".join((*lines, "TER", "END", "")))


def test_mse_axis_preserves_raw_structure_and_excludes_nonpolymer() -> None:
    structure = ProteinStructure(_FIXTURES["mse_ligand_water"]())

    axis = resolve_residue_axis(structure)

    assert axis.structure == structure
    assert axis.layout.residue_ids == ("A:1", "A:2", "A:3")
    assert axis.sequence == "AMG"
    assert axis.residue_names == ("ALA", "MET", "GLY")
    assert axis.coordinate_for("A:2", "SD") == (11.0, 2.0, 3.0)
    assert [
        (item.component_id, item.component_role, item.disposition)
        for item in axis.component_dispositions
    ] == [
        ("ALA", "polymer", "included"),
        ("MSE", "modified_polymer", "normalized"),
        ("GLY", "polymer", "included"),
        ("LIG", "ligand", "excluded"),
        ("HOH", "water", "excluded"),
    ]
    assert RESOLVED_AXIS_PORT_TYPE.decode(
        RESOLVED_AXIS_PORT_TYPE.encode(axis)
    ) == axis
    with pytest.raises(
        PortValueError,
        match="normalized component dispositions and mappings are not closed",
    ):
        RESOLVED_AXIS_PORT_TYPE.encode(
            replace(
                axis,
                modified_residue_normalizations=type(
                    axis.modified_residue_normalizations
                )(),
            )
        )


@pytest.mark.parametrize("missing_record", ["MODRES", "SEQRES"])
def test_mse_requires_both_modres_and_chain_seqres(
    missing_record: str,
) -> None:
    lines = _FIXTURES["mse_ligand_water"]().splitlines()
    structure = ProteinStructure(
        "\n".join(
            line
            for line in lines
            if not line.startswith(missing_record)
        )
        + "\n"
    )

    with pytest.raises(
        ValueError,
        match=r"^unsupported_modified_polymer: MSE at A:2",
    ):
        resolve_residue_axis(structure)


def test_mse_requires_unique_ordered_seqres_correspondence() -> None:
    lines = _FIXTURES["mse_ligand_water"]().splitlines()
    structure = ProteinStructure(
        "\n".join(
            (
                "SEQRES   1 A    5  ALA MSE GLY MSE GLY"
                if line.startswith("SEQRES")
                else line
            )
            for line in lines
        )
        + "\n"
    )

    with pytest.raises(
        ValueError,
        match=r"MSE at A:2 lacks unique SEQRES correspondence$",
    ):
        resolve_residue_axis(structure)


def test_unknown_modified_polymer_rejects_distinctly_from_nonpolymer() -> None:
    structure = ProteinStructure(_FIXTURES["unknown_modified_polymer"]())

    with pytest.raises(
        ValueError,
        match=(
            r"^unsupported_modified_polymer: MLY at A:2 requires an exact "
            r"normalization contract$"
        ),
    ):
        resolve_residue_axis(structure)


def test_unknown_atom_polymer_is_not_guessed_as_sequence_x() -> None:
    structure = ProteinStructure(_FIXTURES["unknown_atom_polymer"]())

    with pytest.raises(
        ValueError,
        match=(
            r"^unsupported_polymer_component: UNK at A:1 requires an exact "
            r"parent contract$"
        ),
    ):
        resolve_residue_axis(structure)


def test_2emo_normalization_repairs_parent_span_topology_and_masks() -> None:
    raw = ProteinStructure((_PROJECT_ROOT / "pdbs" / "2EMO.pdb").read_text())
    with pytest.raises(
        ValueError,
        match=r"^unsupported_modified_polymer: CSH at A:66",
    ):
        resolve_residue_axis(raw)

    normalized, mapping = normalize_csh_parent_span(raw)
    axis = resolve_residue_axis(normalized, mapping)

    assert normalized != raw
    assert normalized.pdb_string.splitlines().count("TER") == 1
    assert axis.structure == normalized
    assert axis.layout.length == 224
    assert len(axis.segments) == 1
    assert axis.segments[0].residue_ids == axis.layout.residue_ids
    index = axis.layout.residue_ids.index("A:64")
    assert axis.layout.residue_ids[index : index + 5] == (
        "A:64",
        "A:65",
        "A:66",
        "A:67",
        "A:68",
    )
    assert axis.sequence[index + 1 : index + 4] == "SHG"
    assert axis.ca_coordinate_mask[index + 1] is True
    assert axis.complete_backbone_mask[index + 1] is False
    assert axis.coordinate_for("A:65", "CA") == pytest.approx(
        (-12.147, 73.489, 39.240)
    )
    assert RESOLVED_AXIS_PORT_TYPE.decode(
        RESOLVED_AXIS_PORT_TYPE.encode(axis)
    ) == axis


def test_csh_normalization_preserves_other_polymer_declarations_for_axis(
) -> None:
    raw, mse_modres, untouched_seqres = _mixed_mse_csh_structure()

    normalized, mapping = normalize_csh_parent_span(raw)
    axis = resolve_residue_axis(normalized, mapping)

    declarations = [
        line
        for line in normalized.pdb_string.splitlines()
        if line.startswith(("MODRES", "SEQRES"))
    ]
    assert declarations == [
        _seqres_line(
            "A",
            ("ALA", "MSE", "GLY", "SER", "HIS", "GLY"),
        ),
        untouched_seqres,
        mse_modres,
    ]
    assert all(
        len(line) == 80
        for line in normalized.pdb_string.splitlines()
        if line.startswith(("ATOM  ", "HETATM", "MODRES", "SEQRES"))
    )
    assert normalized.pdb_string.splitlines()[-1] == "END"
    assert axis.layout.residue_ids == (
        "A:1",
        "A:2",
        "A:3",
        "A:4",
        "A:5",
        "A:6",
    )
    assert axis.sequence == "AMGSHG"
    assert axis.residue_names == (
        "ALA",
        "MET",
        "GLY",
        "SER",
        "HIS",
        "GLY",
    )
    assert [
        (
            item.component_id,
            item.observed_residue_id,
            item.disposition,
        )
        for item in axis.component_dispositions
    ] == [
        ("ALA", "A:1", "included"),
        ("MSE", "A:2", "normalized"),
        ("GLY", "A:3", "included"),
        ("SER", "A:4", "included"),
        ("HIS", "A:5", "included"),
        ("GLY", "A:6", "included"),
        ("CSH", "A:5", "normalized"),
    ]


def test_csh_normalization_rejects_an_internal_ter() -> None:
    lines = _FIXTURES["csh"]().splitlines()
    structure = ProteinStructure("\n".join([lines[0], "TER", *lines[1:]]) + "\n")

    with pytest.raises(
        ValueError,
        match="CSH component coordinate records are noncontiguous",
    ):
        normalize_csh_parent_span(structure)


@pytest.mark.parametrize(
    ("insertion_code", "residue_id"),
    (("", "A:-3"), ("A", "A:-3A")),
)
def test_resolved_axis_preserves_signed_pdb_residue_identity(
    insertion_code: str,
    residue_id: str,
) -> None:
    structure = _signed_residue_structure(insertion_code)

    axis = resolve_residue_axis(structure)

    assert axis.layout.residue_ids == (residue_id,)
    assert axis.segments[0].residue_ids == (residue_id,)
    assert axis.coordinate_for(residue_id, "CA") == (2.0, 2.0, 3.0)
    assert RESOLVED_AXIS_PORT_TYPE.decode(
        RESOLVED_AXIS_PORT_TYPE.encode(axis)
    ) == axis


def test_resolved_axis_canonicalizes_pdb_negative_zero_coordinates() -> None:
    pdb_string = (
        "ATOM      1 CG2  VAL A   1       1.000   2.000  -0.000  "
        "1.00 20.00           C  \n"
        "TER\n"
        "END\n"
    )
    structure = ProteinStructure(pdb_string)

    axis = resolve_residue_axis(structure)

    coordinate = axis.coordinate_for("A:1", "CG2")
    assert axis.structure == structure
    assert "-0.000" in axis.structure.pdb_string
    assert coordinate == (1.0, 2.0, 0.0)
    assert math.copysign(1.0, coordinate[2]) == 1.0
    assert RESOLVED_AXIS_PORT_TYPE.decode(
        RESOLVED_AXIS_PORT_TYPE.encode(axis)
    ) == axis
