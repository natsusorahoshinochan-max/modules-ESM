"""Provider-independent residue identities, layouts, and tracks.

This module owns the shared runtime interface for residue-aligned data:
identity parsing, chain order derivation, immutable freezing, layout/value
closure, identity-addressed reindex, and canonical wire-friendly shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from typing import Any, Generic, TypeVar
import re

from datatypes.candidate import CandidateDataReference
from datatypes.i_json import FrozenList, freeze_i_json


_RESIDUE_IDENTITY = re.compile(
    r"^(?P<chain>[A-Za-z0-9]):(?P<label>"
    r"(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}|[+-][0-9]{1,3}[A-Za-z]?))$"
)

T = TypeVar("T")


def _ordered_tuple(value: object, *, field_name: str) -> tuple:
    if isinstance(value, (list, tuple, FrozenList)):
        return tuple(value)
    raise TypeError(f"{field_name} must be an ordered list or tuple")


def _ordered_frozen(value: object, *, field_name: str) -> FrozenList:
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
            _ordered_frozen(self.entries, field_name="entries"),
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


@dataclass(frozen=True, slots=True)
class ResidueLayout:
    """Ordered, identity-complete target residue layout.

    Only ``residue_ids`` is stored. The length and the chain order are
    derived from the residue identities, so the layout can never contradict
    its own identity axis.
    """

    residue_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "residue_ids",
            FrozenList(
                _ordered_tuple(
                    self.residue_ids,
                    field_name="residue_ids",
                )
            ),
        )

    @property
    def length(self) -> int:
        return len(self.residue_ids)

    @property
    def chain_ids(self) -> tuple[str, ...]:
        """Ordered chains derived from the residue identities."""
        chain_order: list[str] = []
        for residue_id in self.residue_ids:
            chain = residue_identity_chain(residue_id)
            if not chain_order or chain != chain_order[-1]:
                chain_order.append(chain)
        return tuple(chain_order)


def validate_residue_layout(
    value: object,
    *,
    subject: str = "residue layout",
) -> ResidueLayout:
    """Admit one identity-complete layout with contiguous chain boundaries."""
    if type(value) is not ResidueLayout:
        raise ValueError(f"{subject} must be a ResidueLayout")
    if not value.residue_ids:
        raise ValueError(f"{subject} requires one identity for every residue")
    closed_chains: set[str] = set()
    seen_residue_ids: set[str] = set()
    previous_chain: str | None = None
    for index, residue_id in enumerate(value.residue_ids):
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
        previous_chain = chain
    return value


def _freeze_track_value(value: Any) -> Any:
    """Freeze one track value for immutable storage.

    Frozen dataclass carriers (e.g. ``NamedAtomCoordinates``) are stored
    as-is so typed values survive; every other value is frozen through the
    I-JSON projection so wire-encodable track values stay immutable.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return value
    return freeze_i_json(value)


@dataclass(frozen=True, slots=True)
class ResidueTrack(Generic[T]):
    """One nullable value per residue of one exact layout.

    ``values[index]`` always describes ``layout.residue_ids[index]``. The
    carrier does not interpret the scientific role of ``None``; that
    semantics belongs to the nominal Port Type Definition.
    """

    layout: ResidueLayout
    values: tuple[T | None, ...]

    def __post_init__(self) -> None:
        if type(self.layout) is not ResidueLayout:
            raise ValueError("ResidueTrack layout must be a ResidueLayout")
        object.__setattr__(
            self,
            "values",
            FrozenList(
                _freeze_track_value(item)
                for item in _ordered_tuple(
                    self.values,
                    field_name="values",
                )
            ),
        )
        if len(self.values) != self.layout.length:
            raise ValueError(
                "ResidueTrack values length "
                f"{len(self.values)} != layout length {self.layout.length}"
            )

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class CandidateResidueTrack(Generic[T]):
    """One residue track observed for one exact structure Candidate."""

    subject: CandidateDataReference
    track: ResidueTrack[T]

    def __post_init__(self) -> None:
        if type(self.subject) is not CandidateDataReference:
            raise ValueError(
                "CandidateResidueTrack subject must be a CandidateDataReference"
            )
        if type(self.track) is not ResidueTrack:
            raise ValueError(
                "CandidateResidueTrack track must be a ResidueTrack"
            )


def reindex_residue_track(
    track: ResidueTrack,
    target_layout: ResidueLayout,
) -> ResidueTrack:
    """Reindex one track onto a target layout by residue identity.

    Preserved residues keep their values; residues that exist only in the
    target layout receive ``None``. The source layout must cover every
    shared residue identity exactly once.
    """
    if type(track) is not ResidueTrack:
        raise ValueError("reindex expects a ResidueTrack")
    source_index = {
        residue_id: index
        for index, residue_id in enumerate(track.layout.residue_ids)
    }
    if len(source_index) != len(track.values):
        raise ValueError(
            "reindex source layout must be identity-complete"
        )
    values: list[Any] = []
    for residue_id in target_layout.residue_ids:
        index = source_index.get(residue_id)
        values.append(None if index is None else track.values[index])
    return ResidueTrack(target_layout, tuple(values))
