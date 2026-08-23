"""Provider-independent residue identities, layouts, maps, and tracks."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from datatypes.i_json import FrozenList, freeze_i_json


_RESIDUE_IDENTITY = re.compile(
    r"^(?P<chain>[A-Za-z0-9]):(?P<label>"
    r"(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}|[+-][0-9]{1,3}[A-Za-z]?))$"
)

def _ordered_tuple(value: object, *, field_name: str) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return tuple(value)


def _ordered_list(value: object, *, field_name: str) -> FrozenList:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return FrozenList(value)

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
    if residue_ids is None:
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
