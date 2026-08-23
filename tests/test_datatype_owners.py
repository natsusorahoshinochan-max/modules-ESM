"""Provider-independent scientific values have exact, non-re-exporting owners."""

from __future__ import annotations

import datatypes
from typing import get_type_hints

from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ExactPortValueReference,
    ResidueAxisReference,
)
from datatypes.observation import ScoreCollection, ScoreObservation
from datatypes.prediction import (
    ConfidenceFact,
    ConfidenceFactCollection,
    PredictionResidueAxis,
    prediction_axis_reference,
)
from datatypes.prompt import FunctionAnnotation, FunctionAnnotations, ProteinPrompt
from datatypes.residue import ResidueLayout, ResidueMap, ResidueTrack
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure, ResolvedStructureResidueAxis


def test_datatype_package_is_a_marker_with_exact_value_owners() -> None:
    exact_owner_values = (
        Candidate,
        CandidateCollection,
        CandidateDataReference,
        ExactContractReference,
        ExactPortValueReference,
        ResidueAxisReference,
        ScoreCollection,
        ScoreObservation,
        ConfidenceFact,
        ConfidenceFactCollection,
        PredictionResidueAxis,
        FunctionAnnotation,
        FunctionAnnotations,
        ProteinPrompt,
        ResidueLayout,
        ResidueMap,
        ResidueTrack,
        ProteinSequence,
        ProteinStructure,
        ResolvedStructureResidueAxis,
    )

    assert all(value.__module__.startswith("datatypes.") for value in exact_owner_values)
    assert not any(
        hasattr(datatypes, value.__name__)
        for value in exact_owner_values
    )
    assert prediction_axis_reference.__module__ == "datatypes.prediction"
    assert not hasattr(CandidateDataReference, "to_public")
    assert not hasattr(CandidateDataReference, "from_public")
    assert not hasattr(ExactPortValueReference, "to_public")
    assert not hasattr(ResidueAxisReference, "to_public")


def test_exact_reference_annotations_resolve_at_runtime() -> None:
    annotations = get_type_hints(ResidueAxisReference)

    assert annotations["source"] == (
        CandidateDataReference | ExactPortValueReference
    )
