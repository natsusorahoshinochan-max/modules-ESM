"""Format conversion owned by protein I/O, leaving retained source text intact."""
from __future__ import annotations

import re
from typing import Any, Literal, cast
from collections.abc import Mapping

from core.catalog.builtins import restore_candidate_collection_slice
from core.catalog.result_actions import ResultActionDefinition, ResultActionError
from core.parameters.contract import admit_declarations

import gemmi

from datatypes.structure import ProteinStructure
from datatypes.candidate import CandidateDataReference
from datatypes.structure_format import read_mmcif_atoms


class StructureExportError(ValueError):
    """The target format cannot retain the supplied structural identity."""


def convert_structure(
    source: ProteinStructure, target: Literal["pdb", "mmcif"],
) -> ProteinStructure:
    """Serialize all structural components into the explicitly selected format."""
    if source.format == target:
        return source
    if target == "pdb":
        # PDB cannot encode arbitrary mmCIF author labels. Never silently rename
        # or truncate them, including the two-character chain extension in Gemmi.
        for atom in read_mmcif_atoms(source.text):
            if (
                len(atom.chain_id) > 1
                or (atom.chain_id != "" and (not atom.chain_id.isascii() or not atom.chain_id.isalnum()))
                or re.fullmatch(r"-?[0-9]+", atom.residue_number) is None
                or str(int(atom.residue_number)) != atom.residue_number
                or not -999 <= int(atom.residue_number) <= 9999
                or len(atom.insertion_code) > 1
                or (atom.insertion_code and not atom.insertion_code.isalpha())
                or len(atom.atom_name) > 4
                or len(atom.residue_name) > 3
                or len(atom.altloc) > 1
                or not 1 <= int(atom.model) <= 9999
                or any(len(f"{value:.3f}") > 8 for value in atom.coordinate)
            ):
                raise StructureExportError("Structure identities or coordinates cannot be represented in PDB; choose mmCIF")
        structure = gemmi.make_structure_from_block(gemmi.cif.read_string(source.text).sole_block())
        text = structure.make_pdb_string()
        # Gemmi omits MODEL for a single model, even when its number is not 1.
        if len(structure) == 1 and structure[0].num != 1:
            lines = text.splitlines()
            start = next(i for i, line in enumerate(lines) if line.startswith(("ATOM  ", "HETATM")))
            end = max(i for i, line in enumerate(lines) if line.startswith(("ATOM  ", "HETATM", "ANISOU", "TER"))) + 1
            lines.insert(end, "ENDMDL")
            lines.insert(start, f"MODEL     {structure[0].num:4d}")
            text = "\n".join(lines) + "\n"
        return ProteinStructure(text=text, format="pdb")
    structure = gemmi.read_pdb_string(source.text)
    return ProteinStructure(text=structure.make_mmcif_document().as_string(), format="mmcif")


def export_published_structure(body: bytes, parameters: Mapping[str, Any], references: tuple[CandidateDataReference, ...]) -> dict[str, Any]:
    index = parameters["item_index"]
    collection = restore_candidate_collection_slice(body, offset=index, limit=1)
    if index >= collection.total:
        raise ResultActionError("Candidate index is outside the collection")
    if collection.item_type != "protein.structure":
        raise ResultActionError("Selected Candidate has no structure")
    source = cast(ProteinStructure, collection.items[0].data)
    try:
        converted = convert_structure(source, parameters["format"])
    except StructureExportError as error:
        raise ResultActionError(str(error)) from error
    return {"text": converted.text, "format": converted.format}


EXPORT_STRUCTURE_ACTION = ResultActionDefinition(
    action_id="protein_io.export_structure",
    port_type_id="candidate.collection",
    parameters=admit_declarations({
        "item_index": {"parameter_scope": "scientific", "scientific_meaning": "Selected published Candidate index.", "required": True, "value_contract": {"type": "integer", "minimum": 0}},
        "format": {"parameter_scope": "scientific", "scientific_meaning": "Target structure serialization format.", "required": True, "value_contract": {"type": "string", "enum": ["pdb", "mmcif"]}},
    }, path="protein_io.export_structure"),
    apply=export_published_structure,
)
