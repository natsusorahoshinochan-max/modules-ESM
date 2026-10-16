"""Read-only alignment views of chosen axis positions; source structures stay intact."""
from dataclasses import replace
from datatypes.residue import ResidueLayout
from datatypes.structure import ResolvedStructureResidueAxis


def alignment_region_view(axis: ResolvedStructureResidueAxis, residue_ids: tuple[str, ...]) -> ResolvedStructureResidueAxis:
    selected = set(residue_ids)
    indices = [index for index, identity in enumerate(axis.layout.residue_ids) if identity in selected]
    segments = []
    for segment in axis.segments:
        retained = tuple(identity for identity in segment.residue_ids if identity in selected)
        if retained:
            segments.append(replace(segment, segment_index=len(segments), residue_ids=retained))
    return replace(axis, layout=ResidueLayout(residue_ids), sequence=''.join(axis.sequence[index] for index in indices),
                   residue_names=tuple(axis.residue_names[index] for index in indices), segments=tuple(segments),
                   residue_coordinates=tuple(axis.residue_coordinates[index] for index in indices),
                   ca_coordinate_mask=tuple(axis.ca_coordinate_mask[index] for index in indices),
                   complete_backbone_mask=tuple(axis.complete_backbone_mask[index] for index in indices))
