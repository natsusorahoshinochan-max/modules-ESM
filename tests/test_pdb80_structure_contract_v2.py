"""Canonical wwPDB v3.3 coordinate-record admission for structure@4."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.errors import PortValueError
from datatypes.structure import ProteinStructure


_STRUCTURE_TYPE = builtin_frozen_catalog().require_port_type(
    "protein.structure",
    "4.0.0",
)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _coordinate_line(
    *,
    record: str = "ATOM",
    chain_id: str = "A",
    residue_number: int = -3,
    insertion_code: str = "A",
    occupancy: str = "  1.00",
    temperature_factor: str = " 20.00",
    element: str = " C",
    charge: str = "  ",
) -> str:
    line = (
        f"{record:<6}{1:5d} {'CA':^4} {'ALA':>3} "
        f"{chain_id}{residue_number:4d}"
        f"{insertion_code}   "
        f"{1.0:8.3f}{2.0:8.3f}{3.0:8.3f}"
        f"{occupancy}{temperature_factor}"
        f"{'':10}{element}{charge}"
    )
    assert len(line) == 80
    return line


@pytest.mark.parametrize(
    "line",
    (
        _coordinate_line(),
        _coordinate_line(record="HETATM", element="FE", charge="2+"),
    ),
)
def test_structure_v4_admits_complete_pdb80_coordinate_records(line: str) -> None:
    structure = ProteinStructure(f"{line}\nEND\n")

    assert _STRUCTURE_TYPE.decode(_STRUCTURE_TYPE.encode(structure)) == structure


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ((54, 60), "      "),
        ((54, 60), "   nan"),
        ((60, 66), "      "),
        ((60, 66), "   inf"),
        ((76, 78), "  "),
        ((76, 78), "??"),
        ((76, 78), "C "),
        ((78, 80), "+2"),
    ),
)
def test_structure_v4_rejects_invalid_required_pdb80_fields(
    field: tuple[int, int],
    replacement: str,
) -> None:
    line = _coordinate_line()
    start, end = field
    malformed = line[:start] + replacement + line[end:]

    with pytest.raises(PortValueError, match="coordinate record"):
        _STRUCTURE_TYPE.encode(ProteinStructure(f"{malformed}\nEND\n"))


@pytest.mark.parametrize("index", (11, 20, 27, 28, 29, 66, 70, 75))
def test_structure_v4_rejects_nonblank_unassigned_coordinate_columns(
    index: int,
) -> None:
    line = list(_coordinate_line())
    line[index] = "X"

    with pytest.raises(PortValueError, match="coordinate record"):
        _STRUCTURE_TYPE.encode(
            ProteinStructure("".join(line) + "\nEND\n")
        )


@pytest.mark.parametrize(
    ("index", "replacement"),
    (
        (21, " "),
        (21, "-"),
        (26, "1"),
        (26, "-"),
    ),
)
def test_structure_v4_rejects_invalid_coordinate_identity_fields(
    index: int,
    replacement: str,
) -> None:
    line = list(_coordinate_line())
    line[index] = replacement

    with pytest.raises(PortValueError, match="coordinate record"):
        _STRUCTURE_TYPE.encode(
            ProteinStructure("".join(line) + "\nEND\n")
        )


@pytest.mark.parametrize("line", (_coordinate_line()[:-1], _coordinate_line() + " "))
def test_structure_v4_requires_exactly_80_coordinate_columns(line: str) -> None:
    with pytest.raises(PortValueError, match="coordinate record"):
        _STRUCTURE_TYPE.encode(ProteinStructure(f"{line}\nEND\n"))


@pytest.mark.parametrize(
    "filename",
    (
        "1PGA-75-gen1_0690.pdb",
        "2EMO.pdb",
        "3GB1.pdb",
        "5G53.pdb",
    ),
)
def test_tracked_project_pdbs_are_canonical_pdb80(filename: str) -> None:
    structure = ProteinStructure(
        (
            _PROJECT_ROOT / "examples" / "v2" / "structures" / filename
        ).read_text()
    )

    assert _STRUCTURE_TYPE.decode(_STRUCTURE_TYPE.encode(structure)) == structure
