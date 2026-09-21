"""Exact join between complete structure Candidates and their resolved axes.

Only two real consumers need the complete Candidate payload together with its
resolved axis: inserted-loop pass-through and three-way lineage classification.
This module is the single shared implementation of that join. Ordinary
axis-only operations never need it, because the ordered
`structure_transform.candidate_resolved_residue_axis_associations` value already
carries every subject and every axis they use.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from core.operation import AdmittedPort
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ResidueAxisReference
from datatypes.structure import ResolvedStructureResidueAxis

from .domain import CandidateResolvedResidueAxisAssociations


@dataclass(frozen=True, slots=True)
class CandidateWithResolvedResidueAxis:
    """One complete Candidate together with its exact resolved axis."""

    candidate: Candidate
    residue_axis: ResolvedStructureResidueAxis
    axis_reference: ResidueAxisReference


def join_candidate_residue_axes(
    candidates: AdmittedPort,
    residue_axes: AdmittedPort,
) -> Mapping[CandidateDataReference, CandidateWithResolvedResidueAxis]:
    """Join one complete Candidate Collection to its exact resolved axes.

    Both arguments are already admitted scalar collection records. This join
    neither re-admits nor re-validates them: it does not recheck nominal types,
    content digests, or the internal closure of either owner-defined
    projection.

    The one cross-input requirement is that both inputs carry the same set of
    complete Candidate Data References. A missing, extra, or stale reference
    fails with `ValueError`; nothing is repaired, truncated, or defaulted.

    The returned mapping is immutable and iterates in complete Candidate
    Collection order, which is the order its callers pass on unchanged. The
    axis value may hold its entries in another order, because the association
    never relies on position.
    """

    collection: CandidateCollection = candidates.value
    references_by_id = {
        reference.candidate_id: reference
        for reference in candidates.candidate_data
    }
    associations: CandidateResolvedResidueAxisAssociations = residue_axes.value
    axes_by_reference = {
        entry.subject: entry.residue_axis for entry in associations.entries
    }
    if set(axes_by_reference) != set(references_by_id.values()):
        raise ValueError(
            "Candidate residue-axis join requires equal exact Candidate "
            "references on both inputs"
        )
    axis_references_by_source = {
        axis.source: axis for axis in residue_axes.scientific_axes
    }
    joined: dict[
        CandidateDataReference, CandidateWithResolvedResidueAxis
    ] = {}
    for candidate in collection.items:
        reference = references_by_id[candidate.candidate_id]
        joined[reference] = CandidateWithResolvedResidueAxis(
            candidate=candidate,
            residue_axis=axes_by_reference[reference],
            axis_reference=axis_references_by_source[reference],
        )
    return MappingProxyType(joined)


__all__ = [
    "CandidateWithResolvedResidueAxis",
    "join_candidate_residue_axes",
]
