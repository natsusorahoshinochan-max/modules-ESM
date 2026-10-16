"""Exact chain/author-number/insertion selection shared by regional operations."""
from collections.abc import Mapping, Sequence

from datatypes.residue import ResidueLayout


def structure_residue_id(chain_id: str, residue_number: str, insertion_code: str = '') -> str:
    """Use the existing residue-axis identity; never rewrite saved source labels."""
    return f'{chain_id}:{residue_number}{insertion_code}'



def region_residue_ids(layout: ResidueLayout, selection: Sequence[Mapping[str, str]]) -> tuple[str, ...]:
    """Resolve explicit locations against an axis; an empty selection means all."""
    if not selection:
        return tuple(layout.residue_ids)
    requested = tuple(structure_residue_id(item['chain_id'], item['residue_number'], item['insertion_code']) for item in selection)
    if len(set(requested)) != len(requested):
        raise ValueError('region contains duplicate residue locations')
    unknown = set(requested) - set(layout.residue_ids)
    if unknown:
        raise ValueError('region contains residues absent from the input axis: ' + ', '.join(sorted(unknown)))
    selected = set(requested)
    return tuple(identity for identity in layout.residue_ids if identity in selected)
