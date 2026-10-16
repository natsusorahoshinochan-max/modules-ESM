"""mmCIF coordinate reading without reducing authored identities to PDB fields."""
from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from math import isfinite
from typing import Any

from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from Bio.PDB.mmcifio import MMCIFIO


@dataclass(frozen=True, slots=True)
class MmcifAtom:
    record: str
    atom_name: str
    altloc: str
    residue_name: str
    chain_id: str
    residue_number: str
    insertion_code: str
    coordinate: tuple[float, float, float]
    model: str
    label_chain: str


def mmcif_dictionary(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("mmCIF structure text is empty")
    return dict(MMCIF2Dict(StringIO(text)))


def read_mmcif_atoms(text: str) -> tuple[MmcifAtom, ...]:
    """Use author chain/residue labels and retain every atom and model."""
    data = mmcif_dictionary(text)
    count = len(data.get("_atom_site.id", ()))
    if not count:
        raise ValueError("mmCIF structure contains no coordinate records")

    def column(name: str, default: str | None = None) -> list[str]:
        values = data.get("_atom_site." + name)
        if values is None:
            if default is None:
                raise ValueError(f"mmCIF is missing _atom_site.{name}")
            return [default] * count
        if not isinstance(values, list) or len(values) != count:
            raise ValueError(f"mmCIF _atom_site.{name} has inconsistent row count")
        return values

    names = column("auth_atom_id") if "_atom_site.auth_atom_id" in data else column("label_atom_id")
    residues = column("auth_comp_id") if "_atom_site.auth_comp_id" in data else column("label_comp_id")
    chains = column("auth_asym_id") if "_atom_site.auth_asym_id" in data else column("label_asym_id")
    numbers = column("auth_seq_id") if "_atom_site.auth_seq_id" in data else column("label_seq_id")
    atoms = []
    for record, name, alt, residue, chain, number, insertion, x, y, z, model, label_chain in zip(
        column("group_PDB"), names, column("label_alt_id", "."), residues,
        chains, numbers, column("pdbx_PDB_ins_code", "?"), column("Cartn_x"),
        column("Cartn_y"), column("Cartn_z"), column("pdbx_PDB_model_num", "1"),
        column("label_asym_id"), strict=True,
    ):
        coordinate = (float(x), float(y), float(z))
        if record not in {"ATOM", "HETATM"} or not all(isfinite(v) for v in coordinate):
            raise ValueError("mmCIF coordinate record is invalid")
        if chain in {".", "?"} or number in {".", "?"}:
            raise ValueError("mmCIF coordinate record lacks authored residue identity")
        atoms.append(MmcifAtom(
            record, name, " " if alt in {".", "?"} else alt, residue,
            chain, number, "" if insertion in {".", "?"} else insertion,
            coordinate, model, label_chain,
        ))
    return tuple(atoms)


def write_mmcif_dictionary(data: dict[str, Any]) -> str:
    writer = MMCIFIO()
    writer.set_dict(data)
    output = StringIO()
    writer.save(output)
    return output.getvalue().rstrip("\n") + "\n"


def select_mmcif_chains(text: str, chain_ids: tuple[str, ...]) -> str:
    data = mmcif_dictionary(text)
    atoms = read_mmcif_atoms(text)
    indices = [index for chain in chain_ids for index, atom in enumerate(atoms) if atom.chain_id == chain]
    for key, values in tuple(data.items()):
        if key.startswith("_atom_site."):
            data[key] = [values[index] for index in indices]
    return write_mmcif_dictionary(data)
