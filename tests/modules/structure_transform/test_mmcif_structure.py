"""Authored mmCIF identities survive structure operations without PDB truncation."""
from datatypes.structure import ProteinStructure
from datatypes.structure_format import mmcif_dictionary
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from modules.structure_transform.residue_axis import resolve_residue_axis


def test_csh_normalization_preserves_label_gaps_and_unrelated_entities() -> None:
    # Auth columns and insertion codes are optional; the label IDs are the
    # deposited identity in this input. Only entity 1 has observed CSH atoms.
    atoms = [
        "N1", "CA1", "C1", "CB1", "OG2", "N2", "CA2", "C2", "O2",
        "CB2", "CG", "CD2", "ND1", "CE1", "NE2", "N3", "CA3", "C3", "O3",
    ]
    text = """data_csh
loop_
_entity_poly_seq.entity_id
_entity_poly_seq.num
_entity_poly_seq.mon_id
1 1 ALA
1 2 ALA
1 3 ALA
1 4 CSH
1 5 GLY
1 6 GLY
1 7 GLY
2 1 CSH
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
"""
    text += "".join(
        f"HETATM {index} {atom[0]} {atom} CSH Long_chain 1 4 1.0 2.0 3.0\n"
        for index, atom in enumerate(atoms, 1)
    )
    text += "ATOM 20 C CA GLY Long_chain 1 7 4.0 5.0 6.0\n#\n"
    normalized, provenance = normalize_csh_parent_span(ProteinStructure(text, "mmcif"))
    assert normalized.format == "mmcif"
    axis = resolve_residue_axis(normalized, provenance)
    assert axis.layout.residue_ids == (
        "Long_chain:3", "Long_chain:4", "Long_chain:5", "Long_chain:7",
    )
    assert axis.sequence == "SHGG"
    assert axis.coordinate_for("Long_chain:7", "CA") == (4.0, 5.0, 6.0)
    data = mmcif_dictionary(normalized.text)
    assert data["_atom_site.label_seq_id"][-1] == "9"
    entity2 = [
        component for entity, component in zip(
            data["_entity_poly_seq.entity_id"], data["_entity_poly_seq.mon_id"], strict=True,
        ) if entity == "2"
    ]
    assert entity2 == ["CSH"]
    assert provenance.entries[0].observed_residue_id == "Long_chain:4"
    assert provenance.entries[0].parent_residue_ids == (
        "Long_chain:3", "Long_chain:4", "Long_chain:5",
    )
