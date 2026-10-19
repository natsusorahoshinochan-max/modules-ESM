"""Structure helpers still used by the sequence-condition authoring caller."""
from collections import defaultdict
from typing import cast

from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure, ResolvedStructureResidueAxis
from datatypes.structure_format import select_mmcif_chains
from .residue_axis import _coordinate_segments, _renumbered_atom_line, _single_model_records


def select_chains(
    structure: ProteinStructure,
    chain_ids: object,
) -> ProteinStructure:
    """Select exact chain identities and emit them in request order."""
    admitted_chain_ids = cast(tuple[str, ...], chain_ids)
    segments = _coordinate_segments(_single_model_records(structure))
    available = {segment[0].chain_id for segment in segments}
    missing = [
        chain_id for chain_id in admitted_chain_ids if chain_id not in available
    ]
    if missing:
        raise ValueError(
            "requested chains are absent: " + ", ".join(missing)
        )
    if structure.format == "mmcif":
        return ProteinStructure(
            select_mmcif_chains(structure.text, admitted_chain_ids), "mmcif"
        )
    declaration_lines: dict[str, list[str]] = defaultdict(list)
    for line in structure.text.splitlines():
        if line.startswith("SEQRES"):
            if len(line) < 12:
                raise ValueError("PDB SEQRES record has no chain identity")
            declaration_lines[line[11]].append(line)
        elif line.startswith("MODRES"):
            if len(line) < 17:
                raise ValueError("PDB MODRES record has no chain identity")
            declaration_lines[line[16]].append(line)
    output_lines = [
        line
        for chain_id in admitted_chain_ids
        for line in declaration_lines.get(chain_id, ())
    ]
    serial = 1
    for chain_id in admitted_chain_ids:
        for segment in segments:
            if segment[0].chain_id != chain_id:
                continue
            for record in segment:
                output_lines.append(_renumbered_atom_line(record, serial))
                serial += 1
            output_lines.append("TER")
    if not output_lines:
        raise ValueError("chain selection produced no coordinate records")
    output_lines.append("END")
    return ProteinStructure(
        text="\n".join(output_lines) + "\n",
    )


def extract_sequence(
    residue_axis: ResolvedStructureResidueAxis,
) -> ProteinSequence:
    """Project the exact parent sequence and identities from a resolved axis."""
    return ProteinSequence(
        sequence=residue_axis.sequence,
        residue_ids=residue_axis.layout.residue_ids,
    )
