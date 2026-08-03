"""Public protein data types independent of provider SDKs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, is_dataclass
from math import isfinite
import re
from typing import Any, Optional

from datatypes.candidate_reference import CandidateDataReference
from datatypes.identifiers import validate_canonical_identifier
from datatypes.i_json import FrozenList, freeze_i_json, thaw_i_json


_UPPERCASE_AMINO_ACID_ALPHABET = frozenset(
    "ACDEFGHIKLMNPQRSTVWYBXZJUO"
)
_RESIDUE_IDENTITY = re.compile(
    r"^(?P<chain>[A-Za-z0-9]):(?P<label>"
    r"(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}|[+-][0-9]{1,3}[A-Za-z]?))$"
)
_PDB_RECORD_NAMES = frozenset({
    "ANISOU", "ATOM", "AUTHOR", "CAVEAT", "CISPEP", "COMPND", "CONECT",
    "CRYST1", "DBREF", "DBREF1", "DBREF2", "END", "ENDMDL", "EXPDTA",
    "FORMUL", "HEADER", "HELIX", "HET", "HETATM", "HETNAM", "HETSYN",
    "JRNL", "KEYWDS",
    "LINK", "MASTER", "MDLTYP", "MODEL", "MODRES", "MTRIX1", "MTRIX2",
    "MTRIX3", "NUMMDL", "OBSLTE", "ORIGX1", "ORIGX2", "ORIGX3", "REMARK",
    "REVDAT", "SCALE1", "SCALE2", "SCALE3", "SEQADV", "SEQRES", "SHEET",
    "SIGATM", "SIGUIJ", "SITE", "SOURCE", "SPLIT", "SPRSDE", "SSBOND",
    "TER", "TITLE", "TVECT",
})


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


def validate_protein_sequence(
    value: object,
    *,
    subject: str = "protein sequence",
) -> ProteinSequence:
    """Admit one exact sequence and optional canonical residue identities.

    Chain topology is owned by :class:`ResidueLayout`; a sequence therefore
    does not impose contiguous chain boundaries on its optional identities.
    """
    if type(value) is not ProteinSequence:
        raise ValueError(f"{subject} must be a ProteinSequence")
    sequence = value.sequence
    if (
        type(sequence) is not str
        or not sequence
        or any(
            character not in _UPPERCASE_AMINO_ACID_ALPHABET
            for character in sequence
        )
    ):
        raise ValueError(
            f"{subject} must use the exact uppercase amino-acid alphabet"
        )
    residue_ids = value.residue_ids
    if residue_ids is not None and len(residue_ids) != len(sequence):
        raise ValueError(
            f"{subject} residue_ids length must match sequence length"
        )
    seen_residue_ids: set[str] = set()
    for index, residue_id in enumerate(residue_ids or ()):
        residue_identity_chain(
            residue_id,
            subject=f"{subject} residue identity at index {index}",
        )
        if residue_id in seen_residue_ids:
            raise ValueError(
                f"{subject} contains duplicate residue identities"
            )
        seen_residue_ids.add(residue_id)
    return value


@dataclass(frozen=True, slots=True)
class ProteinStructure:
    """Canonical PDB string representation of a protein structure.

    pdb_string: full PDB-format text.
    """

    pdb_string: str


def validate_protein_structure(
    value: object,
    *,
    subject: str = "protein structure",
) -> ProteinStructure:
    """Admit canonical PDB text without imposing operation-specific biology."""
    if type(value) is not ProteinStructure:
        raise ValueError(f"{subject} must be a ProteinStructure")
    pdb_string = value.pdb_string
    if (
        type(pdb_string) is not str
        or not pdb_string
        or not pdb_string.isascii()
        or "\r" in pdb_string
        or "\t" in pdb_string
        or not pdb_string.endswith("\n")
        or pdb_string.endswith("\n\n")
    ):
        raise ValueError(f"{subject} must contain canonical PDB text")

    lines = pdb_string.splitlines()
    record_names = tuple(line[:6].strip() for line in lines)
    if (
        not lines
        or record_names[-1] != "END"
        or lines[-1][6:].strip()
        or "END" in record_names[:-1]
    ):
        raise ValueError(
            f"{subject} canonical PDB text must end with exactly one END record"
        )

    has_model_records = "MODEL" in record_names
    model_is_open = False
    model_coordinate_count = 0
    coordinate_count = 0
    for line_number, (line, record_name) in enumerate(
        zip(lines[:-1], record_names[:-1], strict=True),
        start=1,
    ):
        if record_name not in _PDB_RECORD_NAMES:
            raise ValueError(
                f"{subject} line {line_number} has a non-canonical PDB record"
            )
        if record_name == "MODEL":
            if (
                model_is_open
                or len(line) < 14
                or line[:6] != "MODEL "
                or line[6:10] != "    "
                or not line[10:14].strip().isdigit()
                or int(line[10:14]) <= 0
                or line[14:].strip()
            ):
                raise ValueError(
                    f"{subject} contains non-canonical PDB model boundaries"
                )
            model_is_open = True
            model_coordinate_count = 0
            continue
        if record_name == "ENDMDL":
            if not model_is_open or model_coordinate_count == 0 or line[6:].strip():
                raise ValueError(
                    f"{subject} contains non-canonical PDB model boundaries"
                )
            model_is_open = False
            continue
        if not line.startswith(("ATOM  ", "HETATM")):
            if line.startswith(("ATOM", "HETATM")):
                raise ValueError(
                    f"{subject} line {line_number} is not a canonical PDB "
                    "coordinate record"
                )
            continue
        if has_model_records and not model_is_open:
            raise ValueError(
                f"{subject} contains coordinates outside canonical PDB model "
                "boundaries"
            )
        if len(line) != 80:
            raise ValueError(
                f"{subject} line {line_number} is not a canonical PDB "
                "coordinate record"
            )
        try:
            serial = int(line[6:11])
            int(line[22:26])
            coordinates = tuple(
                float(line[start : start + 8])
                for start in (30, 38, 46)
            )
            occupancy = float(line[54:60])
            temperature_factor = float(line[60:66])
        except ValueError as error:
            raise ValueError(
                f"{subject} line {line_number} is not a canonical PDB "
                "coordinate record"
            ) from error
        element_field = line[76:78]
        element = element_field.strip()
        charge = line[78:80]
        chain_id = line[21]
        insertion_code = line[26]
        if (
            serial <= 0
            or line[11] != " "
            or not line[12:16].strip()
            or not line[17:20].strip()
            or line[20] != " "
            or not chain_id.isascii()
            or not chain_id.isalnum()
            or (
                insertion_code != " "
                and (
                    not insertion_code.isascii()
                    or not insertion_code.isalpha()
                )
            )
            or line[27:30] != "   "
            or line[66:76] != " " * 10
            or not all(
                isfinite(value)
                for value in (
                    *coordinates,
                    occupancy,
                    temperature_factor,
                )
            )
            or not element
            or not element.isalpha()
            or not element.isascii()
            or element_field != element.rjust(2)
            or (
                charge != " " * 2
                and re.fullmatch(r"[0-9][+-]", charge) is None
            )
        ):
            raise ValueError(
                f"{subject} line {line_number} is not a canonical PDB "
                "coordinate record"
            )
        coordinate_count += 1
        model_coordinate_count += 1

    if model_is_open:
        raise ValueError(
            f"{subject} contains non-canonical PDB model boundaries"
        )
    if coordinate_count == 0:
        raise ValueError(
            f"{subject} canonical PDB text must contain a coordinate record"
        )
    return value


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


def residue_identity_chain(
    residue_id: object,
    *,
    subject: str = "residue identity",
) -> str:
    """Return the chain encoded by one canonical residue identity."""
    if type(residue_id) is not str:
        raise ValueError(f"{subject} must be text")
    match = _RESIDUE_IDENTITY.fullmatch(residue_id)
    if match is None:
        raise ValueError(
            f"{subject} {residue_id!r} must be '<chain>:<label>'"
        )
    return match.group("chain")


def validate_residue_layout(
    value: object,
    *,
    subject: str = "residue layout",
) -> ResidueLayout:
    """Admit one identity-complete layout with contiguous chain boundaries."""
    if type(value) is not ResidueLayout:
        raise ValueError(f"{subject} must be a ResidueLayout")
    if type(value.length) is not int or value.length <= 0:
        raise ValueError(f"{subject} length must be positive")
    residue_ids = value.residue_ids
    if residue_ids is None or len(residue_ids) != value.length:
        raise ValueError(f"{subject} requires one identity for every residue")
    chain_order: list[str] = []
    closed_chains: set[str] = set()
    seen_residue_ids: set[str] = set()
    previous_chain: str | None = None
    for index, residue_id in enumerate(residue_ids):
        chain = residue_identity_chain(
            residue_id,
            subject=f"{subject} residue identity at index {index}",
        )
        if residue_id in seen_residue_ids:
            raise ValueError(
                f"{subject} contains duplicate residue identities"
            )
        seen_residue_ids.add(residue_id)
        if chain == previous_chain:
            continue
        if chain in closed_chains:
            raise ValueError(
                f"{subject} chain {chain!r} is not one contiguous boundary"
            )
        if previous_chain is not None:
            closed_chains.add(previous_chain)
        chain_order.append(chain)
        previous_chain = chain

    declared_chain_order = ",".join(chain_order)
    if value.chain_id != declared_chain_order:
        raise ValueError(
            f"{subject} chain_id must equal contiguous chain order "
            f"{declared_chain_order!r}"
        )
    return value


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


def validate_residue_map(
    value: object,
    *,
    subject: str = "residue map",
) -> ResidueMap:
    """Admit one complete, one-to-one, identity-preserving residue map."""
    if type(value) is not ResidueMap:
        raise ValueError(f"{subject} must be a ResidueMap")
    source = validate_residue_layout(
        value.source_layout,
        subject=f"{subject} source layout",
    )
    target = validate_residue_layout(
        value.target_layout,
        subject=f"{subject} target layout",
    )
    source_ids = tuple(source.residue_ids or ())
    target_ids = tuple(target.residue_ids or ())
    common_ids = set(source_ids) & set(target_ids)
    covered_sources: set[int] = set()
    covered_targets: set[int] = set()
    matched_ids: set[str] = set()

    for index, entry in enumerate(value.mappings):
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError(
                f"{subject} mapping at index {index} must be a three-item tuple"
            )
        source_index, target_index, operation = entry
        if type(source_index) is not int or type(target_index) is not int:
            raise ValueError(
                f"{subject} mapping at index {index} requires integer indices"
            )
        if operation == "match":
            if (
                source_index in covered_sources
                or target_index in covered_targets
                or not 0 <= source_index < source.length
                or not 0 <= target_index < target.length
            ):
                raise ValueError(f"{subject} contains overlapping match entries")
            if source_ids[source_index] != target_ids[target_index]:
                raise ValueError(
                    f"{subject} matches contradictory residue identities"
                )
            covered_sources.add(source_index)
            covered_targets.add(target_index)
            matched_ids.add(source_ids[source_index])
            continue
        if operation == "insert":
            if (
                source_index != -1
                or target_index in covered_targets
                or not 0 <= target_index < target.length
                or target_ids[target_index] in common_ids
            ):
                raise ValueError(f"{subject} contains invalid insert entries")
            covered_targets.add(target_index)
            continue
        if operation == "delete":
            if (
                target_index != -1
                or source_index in covered_sources
                or not 0 <= source_index < source.length
                or source_ids[source_index] in common_ids
            ):
                raise ValueError(f"{subject} contains invalid delete entries")
            covered_sources.add(source_index)
            continue
        raise ValueError(
            f"{subject} operation must be match, insert, or delete"
        )

    if covered_sources != set(range(source.length)):
        raise ValueError(f"{subject} does not cover every source residue")
    if covered_targets != set(range(target.length)):
        raise ValueError(f"{subject} does not cover every target residue")
    if matched_ids != common_ids:
        raise ValueError(
            f"{subject} must match every identity preserved by both layouts"
        )
    return value


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


def validate_candidate_parent_ids(
    value: object,
    *,
    subject: str = "Candidate",
) -> Candidate:
    """Admit one ordered, unique list of canonical parent identities."""
    if type(value) is not Candidate:
        raise ValueError(f"{subject} must be a Candidate")
    seen_parent_ids: set[str] = set()
    for index, parent_id in enumerate(value.parent_ids):
        validate_canonical_identifier(
            parent_id,
            f"{subject}.parent_ids[{index}]",
        )
        if parent_id in seen_parent_ids:
            raise ValueError(
                f"{subject} contains duplicate parent identities"
            )
        if parent_id == value.candidate_id:
            raise ValueError(
                f"{subject} contains a cycle (self-parent lineage)"
            )
        seen_parent_ids.add(parent_id)
    return value


def validate_candidate_lineage_graph(
    candidates: tuple[Candidate, ...],
    *,
    subject: str = "Candidate collection",
) -> None:
    """Reject cycles resolved wholly inside one Candidate population.

    Parent identities outside ``candidates`` name admitted upstream Candidates
    and therefore do not participate in this population's internal graph.
    """
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    if len(by_id) != len(candidates):
        raise ValueError(f"{subject} contains duplicate Candidate identities")

    children_by_parent: dict[str, list[str]] = {
        candidate_id: [] for candidate_id in by_id
    }
    unresolved_parent_counts: dict[str, int] = {}
    for candidate_id, candidate in by_id.items():
        internal_parents = tuple(
            parent_id
            for parent_id in candidate.parent_ids
            if parent_id in by_id
        )
        unresolved_parent_counts[candidate_id] = len(internal_parents)
        for parent_id in internal_parents:
            children_by_parent[parent_id].append(candidate_id)

    ready = [
        candidate_id
        for candidate_id, count in unresolved_parent_counts.items()
        if count == 0
    ]
    resolved_count = 0
    while ready:
        parent_id = ready.pop()
        resolved_count += 1
        for child_id in children_by_parent[parent_id]:
            unresolved_parent_counts[child_id] -= 1
            if unresolved_parent_counts[child_id] == 0:
                ready.append(child_id)
    if resolved_count != len(by_id):
        raise ValueError(f"{subject} contains a cycle")


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
class ExactPortValueReference:
    """Exact nominal Port contract and content identity of one input value."""

    port_type: ExactContractReference
    content_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.port_type) is not ExactContractReference
            or self.port_type.contract_kind != "port_type"
        ):
            raise TypeError("port_type must be an exact Port Type reference")
        if (
            type(self.content_digest) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_digest)
            is None
        ):
            raise ValueError(
                "content_digest must be a canonical sha256 digest"
            )

    def to_public(self) -> dict[str, object]:
        return {
            "port_type": {
                "contract_kind": self.port_type.contract_kind,
                "contract_id": self.port_type.contract_id,
                "contract_version": self.port_type.contract_version,
                "contract_digest": self.port_type.contract_digest,
            },
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class ResidueAxisReference:
    """Exact scientific residue axis and the input value that owns it."""

    axis_kind: str
    axis_contract: ExactContractReference
    axis_content_digest: str
    source: CandidateDataReference | ExactPortValueReference
    layout: ResidueLayout

    def __post_init__(self) -> None:
        if self.axis_kind not in {"resolved_structure", "prediction_input"}:
            raise ValueError("axis_kind is not a closed scientific axis kind")
        if (
            type(self.axis_contract) is not ExactContractReference
            or self.axis_contract.contract_kind != "port_type"
        ):
            raise TypeError(
                "axis_contract must be an exact Port Type reference"
            )
        if (
            type(self.axis_content_digest) is not str
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}", self.axis_content_digest
            )
            is None
        ):
            raise ValueError(
                "axis_content_digest must be a canonical sha256 digest"
            )
        if type(self.layout) is not ResidueLayout:
            raise TypeError("layout must be an exact ResidueLayout")
        if self.axis_kind == "resolved_structure":
            if (
                type(self.source) is not CandidateDataReference
                or self.source.data_type_id != "protein.structure"
            ):
                raise TypeError(
                    "resolved_structure axis source must be an exact "
                    "structure CandidateDataReference"
                )
        elif type(self.source) not in {
            CandidateDataReference,
            ExactPortValueReference,
        }:
            raise TypeError(
                "prediction_input axis source must be an exact Candidate "
                "or input Port value reference"
            )

    def to_public(self) -> dict[str, object]:
        source_kind = (
            "candidate_data"
            if type(self.source) is CandidateDataReference
            else "port_value"
        )
        return {
            "axis_kind": self.axis_kind,
            "axis_contract": {
                "contract_kind": self.axis_contract.contract_kind,
                "contract_id": self.axis_contract.contract_id,
                "contract_version": self.axis_contract.contract_version,
                "contract_digest": self.axis_contract.contract_digest,
            },
            "axis_content_digest": self.axis_content_digest,
            "source": {
                "kind": source_kind,
                "reference": self.source.to_public(),
            },
            "layout": {
                "chain_id": self.layout.chain_id,
                "length": self.layout.length,
                "residue_ids": self.layout.residue_ids,
            },
        }


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

    subject: CandidateDataReference
    reference: CandidateDataReference

    def __post_init__(self) -> None:
        if type(self.subject) is not CandidateDataReference:
            raise TypeError(
                "subject must be an exact CandidateDataReference"
            )
        if type(self.reference) is not CandidateDataReference:
            raise TypeError(
                "reference must be an exact CandidateDataReference"
            )


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
    candidate: CandidateDataReference

    def __post_init__(self) -> None:
        if type(self.candidate) is not CandidateDataReference:
            raise TypeError(
                "candidate must be an exact CandidateDataReference"
            )

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def data_type_id(self) -> str:
        return self.candidate.data_type_id

    @property
    def content_digest(self) -> str:
        return self.candidate.content_digest

    def to_public(self) -> dict[str, object]:
        return {
            "role": self.role,
            "candidate": self.candidate.to_public(),
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
    subject_axis_content_digest: str | None = None
    reference_axis_content_digest: str | None = None
    normalization_length: int | None = None
    aligned_atom_count: int | None = None

    def __post_init__(self) -> None:
        evidence = (
            self.evidence_content_digest,
            self.evidence_method,
            self.normalization_length,
            self.aligned_atom_count,
        )
        axis_evidence = (
            self.subject_axis_content_digest,
            self.reference_axis_content_digest,
        )
        if all(item is None for item in evidence):
            if any(item is not None for item in axis_evidence):
                raise ValueError(
                    "Pairwise Context requires complete exact axis provenance"
                )
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
        if any(item is not None for item in axis_evidence) and (
            any(item is None for item in axis_evidence)
            or self.evidence_content_digest is None
            or any(
                type(item) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", item) is None
                for item in axis_evidence
            )
        ):
            raise ValueError(
                "Pairwise Context requires complete exact axis provenance"
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
        if self.subject_axis_content_digest is not None:
            value["subject_axis_content_digest"] = (
                self.subject_axis_content_digest
            )
        if self.reference_axis_content_digest is not None:
            value["reference_axis_content_digest"] = (
                self.reference_axis_content_digest
            )
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

    subject: CandidateDataReference
    metric: ExactContractReference
    method: ExactContractReference
    context: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseObservationContext
    )
    value: object
    residue_axis: ResidueAxisReference | None = None
    source_partition: str = "default"

    def __post_init__(self) -> None:
        if type(self.subject) is not CandidateDataReference:
            raise TypeError(
                "subject must be an exact CandidateDataReference"
            )
        if self.residue_axis is not None and type(
            self.residue_axis
        ) is not ResidueAxisReference:
            raise TypeError(
                "residue_axis must be an exact ResidueAxisReference"
            )
        object.__setattr__(self, "value", freeze_i_json(self.value))

    @property
    def candidate_id(self) -> str:
        """Return the Candidate ID derived from the exact subject."""
        return self.subject.candidate_id

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.subject,
            self.metric,
            self.method,
            self.context,
            self.residue_axis,
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
