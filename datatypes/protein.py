"""Public protein data types independent of provider SDKs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, is_dataclass
import re
from typing import Any, Optional

from datatypes.i_json import FrozenList, freeze_i_json, thaw_i_json


def _ordered_tuple(value: object, *, field_name: str) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return tuple(value)


def _ordered_list(value: object, *, field_name: str) -> FrozenList:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return FrozenList(value)


def _freeze_annotation(value: Any) -> Any:
    parameters = getattr(type(value), "__dataclass_params__", None)
    if is_dataclass(value) and parameters is not None and parameters.frozen:
        return value
    return freeze_i_json(value)


@dataclass(frozen=True, slots=True)
class ProteinSequence:
    """Amino acid sequence with residue identifiers.

    sequence: one-letter amino acid codes (str, no spaces).
    residue_ids: optional list of residue labels matching sequence length.
    """

    sequence: str
    residue_ids: Optional[tuple[str, ...]] = None

    def __post_init__(self) -> None:
        if self.residue_ids is not None:
            object.__setattr__(
                self,
                "residue_ids",
                _ordered_list(self.residue_ids, field_name="residue_ids"),
            )
        if self.residue_ids is not None and len(self.residue_ids) != len(self.sequence):
            raise ValueError(
                f"residue_ids length {len(self.residue_ids)} != sequence length {len(self.sequence)}"
            )

    def __len__(self) -> int:
        return len(self.sequence)


@dataclass(frozen=True, slots=True)
class ProteinStructure:
    """Canonical PDB string representation of a protein structure.

    pdb_string: full PDB-format text.
    """

    pdb_string: str


@dataclass(frozen=True, slots=True)
class ModifiedResidueAtomMapping:
    """One explicit atom mapping from a modified component to its parent."""

    source_atom_name: str
    parent_residue_id: str
    parent_atom_name: str


@dataclass(frozen=True, slots=True)
class ModifiedResidueNormalization:
    """Auditable expansion of one modified component into parent residues."""

    component_id: str
    observed_residue_id: str
    parent_residue_ids: tuple[str, ...]
    parent_sequence: str
    atom_mappings: tuple[ModifiedResidueAtomMapping, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parent_residue_ids",
            _ordered_tuple(
                self.parent_residue_ids,
                field_name="parent_residue_ids",
            ),
        )
        object.__setattr__(
            self,
            "atom_mappings",
            _ordered_tuple(self.atom_mappings, field_name="atom_mappings"),
        )


@dataclass(frozen=True, slots=True)
class ModifiedResidueNormalizationCollection:
    """Closed set of modified-residue normalization records."""

    entries: tuple[ModifiedResidueNormalization, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entries",
            _ordered_list(self.entries, field_name="entries"),
        )


@dataclass(frozen=True, slots=True)
class ResidueLayout:
    """Target residue layout: chain ID and residue count."""

    chain_id: str
    length: int
    residue_ids: Optional[tuple[str, ...]] = None

    def __post_init__(self) -> None:
        if self.residue_ids is not None:
            object.__setattr__(
                self,
                "residue_ids",
                _ordered_list(self.residue_ids, field_name="residue_ids"),
            )
        if self.length < 0:
            raise ValueError(f"length must be >= 0, got {self.length}")
        if self.residue_ids is not None and len(self.residue_ids) != self.length:
            raise ValueError(
                f"residue_ids length {len(self.residue_ids)} != length {self.length}"
            )


@dataclass(frozen=True, slots=True)
class ResidueMap:
    """Mapping from a source (template) layout to a target layout.

    Each entry is (source_idx, target_idx, operation) where operation is
    one of 'match', 'insert', 'delete'.
    """

    source_layout: ResidueLayout
    target_layout: ResidueLayout
    mappings: tuple[tuple[int, int, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mappings",
            FrozenList(
                _ordered_tuple(mapping, field_name="mappings entry")
                for mapping in _ordered_list(
                    self.mappings,
                    field_name="mappings",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ResidueTrack:
    """Per-residue track storing a value or sentinel at each position.

    values: list where each entry is either a concrete value or None (unspecified).
    sentinel: value that means 'not specified' (default None).
    """

    values: tuple[Any, ...] = ()
    sentinel: object = None

    def __post_init__(self) -> None:
        if self.sentinel is not None:
            raise ValueError("ResidueTrack sentinel must be null")
        source_values = _ordered_list(self.values, field_name="values")
        object.__setattr__(
            self,
            "values",
            FrozenList(freeze_i_json(item) for item in source_values),
        )

    def __len__(self) -> int:
        return len(self.values)

    def specified_count(self) -> int:
        return sum(1 for v in self.values if v is not self.sentinel)


@dataclass(frozen=True, slots=True)
class FunctionAnnotations:
    """Named function annotations as residue ranges."""

    annotations: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "annotations",
            FrozenList(
                _freeze_annotation(item)
                for item in _ordered_list(
                    self.annotations,
                    field_name="annotations",
                )
            ),
        )

    def __len__(self) -> int:
        return len(self.annotations)


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class Candidate:
    """A generated sequence or structure with lineage.

    candidate_id: unique identifier.
    data: the underlying ProteinSequence or ProteinStructure.
    parent_ids: list of upstream candidate IDs.
    metadata: arbitrary dict (sample_index, model_name, etc.).
    """

    candidate_id: str
    data: object
    parent_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parent_ids",
            _ordered_list(self.parent_ids, field_name="parent_ids"),
        )
        object.__setattr__(self, "metadata", freeze_i_json(self.metadata))


@dataclass(frozen=True, slots=True)
class CandidateCollection:
    """Collection of Candidates sharing an item type.

    collection_id: unique identifier for this collection.
    item_type: 'protein.sequence' or 'protein.structure'.
    items: list of Candidate references.
    """

    collection_id: str
    item_type: str
    items: tuple[Candidate, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "items",
            _ordered_list(self.items, field_name="items"),
        )

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


@dataclass(frozen=True, slots=True)
class ExactContractReference:
    """Exact versioned scientific contract identity carried by typed values."""

    contract_kind: str
    contract_id: str
    contract_version: str
    contract_digest: str


@dataclass(frozen=True, slots=True)
class IntrinsicObservationContext:
    """The one closed Context for an intrinsic Candidate measurement."""

    kind: str = "intrinsic"

    def to_public(self) -> dict[str, str]:
        return {"kind": self.kind}


@dataclass(frozen=True, slots=True)
class CalibrationObservationContext:
    """A fixed population baseline required to interpret an Observation."""

    calibration_metric: str
    calibration_value: float
    calibration_unit: str
    population_id: str
    kind: str = "calibration"

    def to_public(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "calibration_metric": self.calibration_metric,
            "calibration_value": self.calibration_value,
            "calibration_unit": self.calibration_unit,
            "population_id": self.population_id,
        }


@dataclass(frozen=True, slots=True)
class PairwiseCandidateMatch:
    """One explicit subject-to-reference Candidate relationship."""

    subject_candidate_id: str
    subject_content_digest: str
    reference_candidate_id: str
    reference_content_digest: str


@dataclass(frozen=True, slots=True)
class PairwiseCandidateMapping:
    """Closed per-subject counterpart mapping carried through a typed Port."""

    entries: tuple[PairwiseCandidateMatch, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entries",
            _ordered_list(self.entries, field_name="entries"),
        )


@dataclass(frozen=True, slots=True)
class PairwiseParticipant:
    """One role-labelled Candidate participating in a pairwise observation."""

    role: str
    candidate_id: str
    content_digest: str

    def to_public(self) -> dict[str, str]:
        return {
            "role": self.role,
            "candidate_id": self.candidate_id,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class PairwiseObservationContext:
    """Exact subject/reference relationship defining a pairwise observation."""

    subject: PairwiseParticipant
    reference: PairwiseParticipant
    pairing_mode: str
    normalization: str
    kind: str = "pairwise"
    evidence_content_digest: str | None = None
    evidence_method: ExactContractReference | None = None
    normalization_length: int | None = None
    aligned_atom_count: int | None = None

    def __post_init__(self) -> None:
        evidence = (
            self.evidence_content_digest,
            self.evidence_method,
            self.normalization_length,
            self.aligned_atom_count,
        )
        if all(item is None for item in evidence):
            return
        if (
            any(item is None for item in evidence)
            or not isinstance(self.evidence_content_digest, str)
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                self.evidence_content_digest,
            )
            is None
            or type(self.evidence_method) is not ExactContractReference
            or self.evidence_method.contract_kind != "method"
            or type(self.normalization_length) is not int
            or self.normalization_length < 1
            or type(self.aligned_atom_count) is not int
            or self.aligned_atom_count < 1
            or self.aligned_atom_count > self.normalization_length
        ):
            raise ValueError(
                "Pairwise Context requires complete exact evidence provenance"
            )

    def to_public(self) -> dict[str, object]:
        value: dict[str, object] = {
            "kind": self.kind,
            "subject": self.subject.to_public(),
            "reference": self.reference.to_public(),
            "pairing_mode": self.pairing_mode,
            "normalization": self.normalization,
        }
        if self.evidence_content_digest is not None:
            value["evidence_content_digest"] = self.evidence_content_digest
        if self.evidence_method is not None:
            value["evidence_method"] = {
                "contract_kind": self.evidence_method.contract_kind,
                "contract_id": self.evidence_method.contract_id,
                "contract_version": self.evidence_method.contract_version,
                "contract_digest": self.evidence_method.contract_digest,
            }
        if self.normalization_length is not None:
            value["normalization_length"] = self.normalization_length
        if self.aligned_atom_count is not None:
            value["aligned_atom_count"] = self.aligned_atom_count
        return value


@dataclass(frozen=True, slots=True)
class ScoreObservation:
    """A scientifically typed Candidate measurement.

    ``value`` is interpreted by the exact Metric, Method, and Context but is
    intentionally excluded from ``identity``.
    """

    candidate_id: str
    metric: ExactContractReference
    method: ExactContractReference
    context: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseObservationContext
    )
    value: object
    source_partition: str = "default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", freeze_i_json(self.value))

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.candidate_id,
            self.metric,
            self.method,
            self.context,
        )


@dataclass(frozen=True, slots=True)
class ScoreCollection:
    """Ordered scientifically typed v2 Score Observations."""

    collection_id: str
    entries: tuple[ScoreObservation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entries",
            _ordered_list(self.entries, field_name="entries"),
        )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def manifest_facts(self) -> Iterator[dict[str, object]]:
        """Yield Candidate-bound scores for bounded durable provenance."""
        for entry in self.entries:
            yield {
                "kind": "candidate_score_observation",
                "candidate_id": entry.candidate_id,
                "metric": {
                    "contract_kind": entry.metric.contract_kind,
                    "contract_id": entry.metric.contract_id,
                    "contract_version": entry.metric.contract_version,
                    "contract_digest": entry.metric.contract_digest,
                },
                "method": {
                    "contract_kind": entry.method.contract_kind,
                    "contract_id": entry.method.contract_id,
                    "contract_version": entry.method.contract_version,
                    "contract_digest": entry.method.contract_digest,
                },
                "context": entry.context.to_public(),
                "source_partition": entry.source_partition,
                "value": thaw_i_json(entry.value),
            }


@dataclass(frozen=True, slots=True)
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

    residue_map: tuple[tuple[str, str], ...] = ()
    chain_map: Mapping[str, str] = field(default_factory=dict)
    rotation: tuple[tuple[float, ...], ...] = ()
    translation: tuple[float, ...] = ()
    rmsd: float = 0.0
    coverage: float = 0.0
    reference_sequence: str = ""
    mobile_sequence: str = ""
    reference_length: int = 0
    mobile_length: int = 0
    aligned_reference_indices: tuple[int, ...] = ()
    aligned_mobile_indices: tuple[int, ...] = ()
    aligned_reference_coordinates: tuple[tuple[float, ...], ...] = ()
    aligned_mobile_coordinates: tuple[tuple[float, ...], ...] = ()
    aligned_distances: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "residue_map",
            FrozenList(
                _ordered_tuple(pair, field_name="residue_map entry")
                for pair in _ordered_list(
                    self.residue_map,
                    field_name="residue_map",
                )
            ),
        )
        object.__setattr__(self, "chain_map", freeze_i_json(self.chain_map))
        for name in (
            "rotation",
            "aligned_reference_coordinates",
            "aligned_mobile_coordinates",
        ):
            object.__setattr__(
                self,
                name,
                FrozenList(
                    _ordered_list(row, field_name=f"{name} row")
                    for row in _ordered_list(
                        getattr(self, name),
                        field_name=name,
                    )
                ),
            )
        for name in (
            "translation",
            "aligned_reference_indices",
            "aligned_mobile_indices",
            "aligned_distances",
        ):
            object.__setattr__(
                self,
                name,
                _ordered_list(getattr(self, name), field_name=name),
            )


@dataclass(frozen=True, slots=True)
class ProteinMPNNConstraints:
    """Residue-level constraints for ProteinMPNN design.

    Residues are addressed by stable identities from the complete target
    layout. The ProteinMPNN Adapter performs the single conversion to upstream
    one-based, chain-qualified positions.

    ``designable_residue_ids`` is a whitelist within the designed chains;
    unlisted residues are fixed. ``fixed_residue_ids`` fixes individual
    residues. ``designed_chains`` and ``fixed_chains`` select the chain
    partition. ``omit_amino_acids`` is a global sampling exclusion.
    ``tied_residue_groups`` contains identity groups sampled as the same amino
    acid. ``bias_by_residue`` maps identities to per-amino-acid logit biases.
    None means no constraint in that dimension.
    """
    layout: ResidueLayout
    designable_residue_ids: Optional[tuple[str, ...]] = None
    fixed_residue_ids: Optional[tuple[str, ...]] = None
    designed_chains: Optional[tuple[str, ...]] = None
    fixed_chains: Optional[tuple[str, ...]] = None
    omit_amino_acids: Optional[tuple[str, ...]] = None
    tied_residue_groups: Optional[tuple[tuple[str, ...], ...]] = None
    bias_by_residue: Optional[Mapping[str, Mapping[str, float]]] = None

    def __post_init__(self) -> None:
        for name in (
            "designable_residue_ids",
            "fixed_residue_ids",
            "designed_chains",
            "fixed_chains",
            "omit_amino_acids",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _ordered_list(value, field_name=name),
                )
        if self.tied_residue_groups is not None:
            object.__setattr__(
                self,
                "tied_residue_groups",
                FrozenList(
                    _ordered_list(
                        group,
                        field_name="tied_residue_groups entry",
                    )
                    for group in _ordered_list(
                        self.tied_residue_groups,
                        field_name="tied_residue_groups",
                    )
                ),
            )
        if self.bias_by_residue is not None:
            object.__setattr__(
                self,
                "bias_by_residue",
                freeze_i_json(self.bias_by_residue),
            )
