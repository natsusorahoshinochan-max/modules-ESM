"""Provider-independent Candidate identity, lineage, and collections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from datatypes.i_json import FrozenList, freeze_i_json


def _ordered_list(value: object, *, field_name: str) -> FrozenList:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return FrozenList(value)


_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CandidateDataReference:
    """Canonical content identity of one Candidate's data value."""

    candidate_id: str
    data_type_id: str
    content_digest: str

    def __post_init__(self) -> None:
        from datatypes.exact_reference import validate_canonical_identifier

        for field_name in ("candidate_id", "data_type_id"):
            validate_canonical_identifier(getattr(self, field_name), field_name)
        if (
            type(self.content_digest) is not str
            or _CONTENT_DIGEST.fullmatch(self.content_digest) is None
        ):
            raise ValueError(
                "content_digest must be a canonical sha256 digest"
            )

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
    from datatypes.exact_reference import validate_canonical_identifier

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
