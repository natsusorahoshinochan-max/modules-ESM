"""Scientific values shared by sequence-solubility providers."""

from __future__ import annotations

from dataclasses import dataclass

from datatypes.candidate import CandidateDataReference
from datatypes.sequence import ProteinSequence


@dataclass(frozen=True, slots=True)
class SequenceSolubilitySubject:
    """One exact admitted sequence subject crossing the Adapter seam."""

    subject: CandidateDataReference
    sequence: ProteinSequence
