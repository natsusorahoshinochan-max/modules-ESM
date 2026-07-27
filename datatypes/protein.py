"""Public protein data types independent of provider SDKs."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProteinSequence:
    """Amino acid sequence with residue identifiers.

    sequence: one-letter amino acid codes (str, no spaces).
    residue_ids: optional list of residue labels matching sequence length.
    """

    sequence: str
    residue_ids: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if self.residue_ids is not None and len(self.residue_ids) != len(self.sequence):
            raise ValueError(
                f"residue_ids length {len(self.residue_ids)} != sequence length {len(self.sequence)}"
            )

    def __len__(self) -> int:
        return len(self.sequence)


@dataclass
class ProteinStructure:
    """Canonical PDB string representation of a protein structure.

    pdb_string: full PDB-format text.
    source: optional provenance label (e.g. 'esm3', 'esmfold2', 'simplefold').
    """

    pdb_string: str
    source: Optional[str] = None


@dataclass
class ResidueLayout:
    """Target residue layout: chain ID and residue count."""

    chain_id: str
    length: int
    residue_ids: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if self.length < 0:
            raise ValueError(f"length must be >= 0, got {self.length}")
        if self.residue_ids is not None and len(self.residue_ids) != self.length:
            raise ValueError(
                f"residue_ids length {len(self.residue_ids)} != length {self.length}"
            )


@dataclass
class ResidueMap:
    """Mapping from a source (template) layout to a target layout.

    Each entry is (source_idx, target_idx, operation) where operation is
    one of 'match', 'insert', 'delete'.
    """

    source_layout: ResidueLayout
    target_layout: ResidueLayout
    mappings: list[tuple[int, int, str]] = field(default_factory=list)


@dataclass
class ResidueTrack:
    """Per-residue track storing a value or sentinel at each position.

    values: list where each entry is either a concrete value or None (unspecified).
    sentinel: value that means 'not specified' (default None).
    """

    values: list = field(default_factory=list)
    sentinel: object = None

    def __len__(self) -> int:
        return len(self.values)

    def specified_count(self) -> int:
        return sum(1 for v in self.values if v is not self.sentinel)


@dataclass
class FunctionAnnotations:
    """Named function annotations as residue ranges."""

    annotations: list[dict] = field(default_factory=list)

    def add(self, label: str, start: int, end: int) -> None:
        self.annotations.append({"label": label, "start": start, "end": end})

    def __len__(self) -> int:
        return len(self.annotations)


@dataclass
class ProteinPrompt:
    """Multi-track protein prompt for ESM3 conditioning.

    All per-residue tracks must have length equal to the target layout length.
    Each track is fully independent.
    """

    target_layout: Optional[ResidueLayout] = None
    sequence_track: Optional[ResidueTrack] = None
    structure_track: Optional[ResidueTrack] = None
    structure_visibility_track: Optional[ResidueTrack] = None
    secondary_structure_track: Optional[ResidueTrack] = None
    sasa_track: Optional[ResidueTrack] = None
    function_annotations: FunctionAnnotations = field(default_factory=FunctionAnnotations)

    @property
    def num_residues(self) -> int:
        if self.target_layout is not None:
            return self.target_layout.length
        return 0


@dataclass
class Candidate:
    """A generated sequence or structure with lineage.

    candidate_id: unique identifier.
    data: the underlying ProteinSequence or ProteinStructure.
    parent_ids: list of upstream candidate IDs.
    metadata: arbitrary dict (sample_index, model_name, etc.).
    """

    candidate_id: str
    data: object
    parent_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class CandidateCollection:
    """Collection of Candidates sharing an item type.

    collection_id: unique identifier for this collection.
    item_type: 'protein.sequence' or 'protein.structure'.
    items: list of Candidate references.
    """

    collection_id: str
    item_type: str
    items: list[Candidate] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def manifest_facts(self) -> list[dict[str, object]]:
        """Describe lineage without requiring the engine to inspect this type."""
        return [
            {
                "kind": "candidate_lineage",
                "candidate_id": candidate.candidate_id,
                "parent_ids": list(candidate.parent_ids),
            }
            for candidate in self.items
        ]


@dataclass
class Score:
    """A single score entry.

    score_id: identifier for the score type (e.g. 'plddt', 'tm_score').
    value: numeric score value.
    subjects: list of references (candidate IDs, structure IDs, etc.).
    details: optional extra data (per-residue values, etc.).
    """

    score_id: str
    value: float
    subjects: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class ScoreCollection:
    """Set of score entries produced by a scoring module."""

    collection_id: str
    entries: list[Score] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def manifest_facts(self) -> Iterator[dict[str, object]]:
        """Yield Candidate-bound scores for bounded durable provenance."""
        for entry in self.entries:
            yield {
                "kind": "candidate_score",
                "score_id": entry.score_id,
                "value": entry.value,
                "subjects": list(entry.subjects),
                "details": dict(entry.details),
            }


@dataclass
class StructureAlignment:
    """Result of superimposing two protein structures.

    residue_map: PDB provenance labels for aligned (reference, mobile) residues.
    chain_map: dict mapping reference chain -> mobile chain.
    rotation: 3x3 rotation matrix.
    translation: 3-vector translation.
    rmsd: RMSD in angstroms.
    coverage: fraction of aligned residues (0-1).
    reference_sequence: one-letter sequence of reference residues with CA atoms.
    mobile_sequence: one-letter sequence of mobile residues with CA atoms.
    reference_length: number of reference residues available for alignment.
    mobile_length: number of mobile residues available for alignment.
    aligned_reference_indices: zero-based reference indices in correspondence order.
    aligned_mobile_indices: zero-based mobile indices in correspondence order.
    aligned_reference_coordinates: reference CA coordinates in correspondence order.
    aligned_mobile_coordinates: mobile CA coordinates before applying the transform.
    aligned_distances: per-pair distances after transforming the mobile coordinates.

    The transform follows Bio.SVDSuperimposer's row-vector convention:
    ``mobile @ rotation + translation``.
    """

    residue_map: list[tuple[str, str]] = field(default_factory=list)
    chain_map: dict[str, str] = field(default_factory=dict)
    rotation: list[list[float]] = field(default_factory=list)
    translation: list[float] = field(default_factory=list)
    rmsd: float = 0.0
    coverage: float = 0.0
    reference_sequence: str = ""
    mobile_sequence: str = ""
    reference_length: int = 0
    mobile_length: int = 0
    aligned_reference_indices: list[int] = field(default_factory=list)
    aligned_mobile_indices: list[int] = field(default_factory=list)
    aligned_reference_coordinates: list[list[float]] = field(default_factory=list)
    aligned_mobile_coordinates: list[list[float]] = field(default_factory=list)
    aligned_distances: list[float] = field(default_factory=list)


@dataclass
class ProteinMPNNConstraints:
    """Residue-level constraints for ProteinMPNN design.

    Residue positions are zero-based indices into the complete target layout in
    structure-chain order.  The ProteinMPNN adapter performs the single
    conversion to upstream one-based, chain-qualified positions.

    ``designable_positions`` is a whitelist within the designed chains;
    unlisted positions are fixed. ``fixed_positions`` fixes individual
    positions. ``designed_chains`` and ``fixed_chains`` select the chain
    partition. ``omit_amino_acids`` is a global sampling exclusion.
    ``tied_positions`` contains groups of positions sampled as the same amino
    acid. ``bias_by_res`` maps positions to per-amino-acid logit biases.
    None means no constraint in that dimension.
    """
    designable_positions: Optional[list[int]] = None
    fixed_positions: Optional[list[int]] = None
    designed_chains: Optional[list[str]] = None
    fixed_chains: Optional[list[str]] = None
    omit_amino_acids: Optional[list[str]] = None
    tied_positions: Optional[list[list[int]]] = None
    bias_by_res: Optional[dict[int, dict[str, float]]] = None
