"""Direct implementations for exact role-labelled structure comparison."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    PairwiseCandidateMapping,
    PairwiseObservationContext,
    PairwiseParticipant,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
)
from modules.structure_alignment import align_structures

from .domain import (
    AlignmentAtomCorrespondence,
    StructureAlignmentEvidence,
    StructureAlignmentEvidenceCollection,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
)


_VERSION = "2.0.0"
_ALIGNMENT_METHOD = "structure_comparison.ca_sequence_svd.method"
_RMSD_METHOD = "structure_comparison.rmsd.method"
_RMSD_METRIC = "structure_comparison.rmsd"
_NORMALIZATION = "ca-correspondence-mean-square-angstrom"


class StructureComparisonImplementation:
    """Dispatch the package's three Node Types through one implementation."""

    def __init__(
        self,
        run_resources: Any,
        catalog: Any,
        operation: str,
        pairing_mode: str | None = None,
    ) -> None:
        self._run_resources = run_resources
        self._catalog = catalog
        self._operation = operation
        self._pairing_mode = pairing_mode

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError(
                "structure comparison Nodes do not accept parameters"
            )
        if self._operation == "align_single":
            return self._align_single(inputs)
        if self._operation == "align_pairwise":
            return self._align_pairwise(inputs)
        if self._operation == "rmsd":
            return self._observe_rmsd(inputs)
        raise RuntimeError("unknown structure comparison operation")

    def _reference(
        self,
        kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = self._catalog.require_contract(
            kind,
            contract_id,
            _VERSION,
        )
        return ExactContractReference(**contract.reference())

    def _candidates(
        self,
        value: object,
        *,
        role: str,
    ) -> tuple[tuple[Candidate, str], ...]:
        if (
            type(value) is not CandidateCollection
            or value.item_type != "protein.structure"
            or not value.items
        ):
            raise ValueError(
                f"{role} must be a non-empty protein structure "
                "Candidate Collection"
            )
        ids: set[str] = set()
        result: list[tuple[Candidate, str]] = []
        codec = self._catalog.require_port_type(
            "protein.structure",
            _VERSION,
        )
        for candidate in value.items:
            if (
                type(candidate) is not Candidate
                or not candidate.candidate_id
                or type(candidate.data) is not ProteinStructure
            ):
                raise ValueError(
                    f"{role} contains an incomplete structure Candidate"
                )
            if candidate.candidate_id in ids:
                raise ValueError(f"{role} contains duplicate Candidate identities")
            ids.add(candidate.candidate_id)
            result.append(
                (candidate, codec.content_digest(candidate.data))
            )
        return tuple(result)

    @staticmethod
    def _by_id(
        candidates: tuple[tuple[Candidate, str], ...],
    ) -> dict[str, tuple[Candidate, str]]:
        return {
            candidate.candidate_id: (candidate, digest)
            for candidate, digest in candidates
        }

    def _alignment(
        self,
        *,
        subject: Candidate,
        subject_digest: str,
        reference: Candidate,
        reference_digest: str,
        engine_role: str,
    ) -> StructureAlignmentEvidence:
        if subject.candidate_id == reference.candidate_id:
            raise ValueError(
                "subject and reference Candidate identities must differ"
            )
        native = align_structures(
            reference.data,
            subject.data,
            separate_tiebreak_evidence=True,
            engine_invocation=self._run_resources.engine_invocation,
        )
        count = len(native.residue_map)
        evidence_lengths = {
            count,
            len(native.aligned_reference_indices),
            len(native.aligned_mobile_indices),
            len(native.aligned_reference_coordinates),
            len(native.aligned_mobile_coordinates),
            len(native.aligned_distances),
        }
        if count == 0 or len(evidence_lengths) != 1:
            raise ValueError(
                "alignment engine returned incomplete atom correspondence"
            )
        if (
            native.reference_length < count
            or native.mobile_length < count
        ):
            raise ValueError(
                "alignment correspondence exceeds the input structures"
            )
        rotation = tuple(
            tuple(float(item) for item in row)
            for row in native.rotation
        )
        translation = tuple(float(item) for item in native.translation)
        correspondence = tuple(
            AlignmentAtomCorrespondence(
                subject_residue_id=subject_residue,
                subject_atom_name="CA",
                subject_coordinate=tuple(
                    float(item) for item in subject_coordinate
                ),
                reference_residue_id=reference_residue,
                reference_atom_name="CA",
                reference_coordinate=tuple(
                    float(item) for item in reference_coordinate
                ),
                transformed_subject_coordinate=tuple(
                    math.fsum(
                        float(subject_coordinate[index])
                        * rotation[index][axis]
                        for index in range(3)
                    )
                    + translation[axis]
                    for axis in range(3)
                ),
                residual_distance=float(distance),
            )
            for (
                reference_residue,
                subject_residue,
            ), reference_coordinate, subject_coordinate, distance in zip(
                native.residue_map,
                native.aligned_reference_coordinates,
                native.aligned_mobile_coordinates,
                native.aligned_distances,
                strict=True,
            )
        )
        return StructureAlignmentEvidence(
            schema_version=_VERSION,
            subject=PairwiseParticipant(
                role="subject",
                candidate_id=subject.candidate_id,
                content_digest=subject_digest,
            ),
            reference=PairwiseParticipant(
                role="reference",
                candidate_id=reference.candidate_id,
                content_digest=reference_digest,
            ),
            correspondence=correspondence,
            transform=StructureAlignmentTransform(
                maps_from_role="subject",
                maps_to_role="reference",
                row_vector_rotation=rotation,
                translation=translation,
            ),
            normalization=StructureAlignmentNormalization(
                atom_selection="CA",
                subject_residue_count=native.mobile_length,
                reference_residue_count=native.reference_length,
                aligned_atom_count=count,
                coverage_denominator=(
                    "max(subject_residue_count,reference_residue_count)"
                ),
            ),
            rmsd=float(native.rmsd),
            coverage=float(native.coverage),
            method=self._reference("method", _ALIGNMENT_METHOD),
        )

    def _align_single(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(inputs) != {"subjects", "references"}:
            raise ValueError(
                "single alignment requires subjects and references"
            )
        subjects = self._candidates(inputs["subjects"], role="subjects")
        references = self._candidates(
            inputs["references"],
            role="references",
        )
        if len(subjects) != 1 or len(references) != 1:
            raise ValueError(
                "single alignment requires exactly one subject and reference"
            )
        subject, subject_digest = subjects[0]
        reference, reference_digest = references[0]
        return {
            "alignment": self._alignment(
                subject=subject,
                subject_digest=subject_digest,
                reference=reference,
                reference_digest=reference_digest,
                engine_role="single_alignment",
            )
        }

    def _pairing(
        self,
        value: object,
        *,
        subjects: tuple[tuple[Candidate, str], ...],
        references: tuple[tuple[Candidate, str], ...],
    ) -> tuple[
        tuple[
            tuple[Candidate, str],
            tuple[Candidate, str],
        ],
        ...,
    ]:
        if type(value) is not PairwiseCandidateMapping or not value.entries:
            raise ValueError(
                "pairwise alignment requires an explicit Candidate pairing"
            )
        if (
            len(value.entries) != len(subjects)
            or len(value.entries) != len(references)
        ):
            raise ValueError(
                "pairwise alignment requires complete one-to-one cardinality"
            )
        subjects_by_id = self._by_id(subjects)
        references_by_id = self._by_id(references)
        if set(subjects_by_id).intersection(references_by_id):
            raise ValueError(
                "subject and reference Candidate identity sets must be disjoint"
            )
        if {
            entry.subject_candidate_id for entry in value.entries
        } != set(subjects_by_id) or {
            entry.reference_candidate_id for entry in value.entries
        } != set(references_by_id):
            raise ValueError(
                "pairing must cover every subject and reference exactly once"
            )
        pairs: list[
            tuple[tuple[Candidate, str], tuple[Candidate, str]]
        ] = []
        for entry in value.entries:
            subject = subjects_by_id[entry.subject_candidate_id]
            reference = references_by_id[entry.reference_candidate_id]
            if (
                entry.subject_content_digest != subject[1]
                or entry.reference_content_digest != reference[1]
            ):
                raise ValueError(
                    "pairing Candidate identity conflicts with exact content"
                )
            pairs.append((subject, reference))
        return tuple(pairs)

    def _align_pairwise(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(inputs) != {"subjects", "references", "pairing"}:
            raise ValueError(
                "pairwise alignment requires subjects, references, and pairing"
            )
        subjects = self._candidates(inputs["subjects"], role="subjects")
        references = self._candidates(
            inputs["references"],
            role="references",
        )
        pairs = self._pairing(
            inputs["pairing"],
            subjects=subjects,
            references=references,
        )
        alignments = tuple(
            self._alignment(
                subject=subject,
                subject_digest=subject_digest,
                reference=reference,
                reference_digest=reference_digest,
                engine_role=f"pair_alignment_{index}",
            )
            for index, (
                (subject, subject_digest),
                (reference, reference_digest),
            ) in enumerate(pairs)
        )
        return {
            "alignments": StructureAlignmentEvidenceCollection(
                schema_version=_VERSION,
                pairing_source="candidate.pairing@2.0.0",
                accepted_cardinality="one_to_one_complete",
                alignments=alignments,
            )
        }

    @staticmethod
    def _rmsd(alignment: StructureAlignmentEvidence) -> float:
        count = alignment.normalization.aligned_atom_count
        if count != len(alignment.correspondence) or count < 1:
            raise ValueError("RMSD requires complete non-empty correspondence")
        value = float(alignment.rmsd)
        if not math.isfinite(value):
            raise ValueError("RMSD must be finite")
        return value

    def _assert_alignment_method(
        self,
        alignment: StructureAlignmentEvidence,
    ) -> None:
        if alignment.method != self._reference(
            "method",
            _ALIGNMENT_METHOD,
        ):
            raise ValueError(
                "alignment evidence names a conflicting Method identity"
            )

    @staticmethod
    def _assert_alignment_identity(
        alignment: StructureAlignmentEvidence,
        subject: tuple[Candidate, str],
        reference: tuple[Candidate, str],
    ) -> None:
        if (
            alignment.subject.candidate_id != subject[0].candidate_id
            or alignment.subject.content_digest != subject[1]
            or alignment.reference.candidate_id
            != reference[0].candidate_id
            or alignment.reference.content_digest != reference[1]
        ):
            raise ValueError(
                "alignment evidence conflicts with exact Candidate inputs"
            )

    def _observation(
        self,
        alignment: StructureAlignmentEvidence,
        *,
        pairing_mode: str,
    ) -> ScoreObservation:
        with self._run_resources.engine_invocation(
            engine_role="rmsd_observation",
            engine_identity="structure_comparison.rmsd/2.0.0",
        ):
            value = self._rmsd(alignment)
        return ScoreObservation(
            candidate_id=alignment.subject.candidate_id,
            metric=self._reference("metric", _RMSD_METRIC),
            method=self._reference("method", _RMSD_METHOD),
            context=PairwiseObservationContext(
                subject=alignment.subject,
                reference=alignment.reference,
                pairing_mode=pairing_mode,
                normalization=_NORMALIZATION,
            ),
            value=value,
            source_partition="structure_comparison.rmsd",
        )

    def _observe_rmsd(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self._pairing_mode == "fixed_reference":
            if set(inputs) != {"alignment", "subjects", "references"}:
                raise ValueError(
                    "fixed-reference RMSD requires alignment, subjects, and "
                    "references"
                )
            subjects = self._candidates(inputs["subjects"], role="subjects")
            references = self._candidates(
                inputs["references"],
                role="references",
            )
            alignment = inputs["alignment"]
            if (
                type(alignment) is not StructureAlignmentEvidence
                or len(subjects) != 1
                or len(references) != 1
            ):
                raise ValueError(
                    "fixed-reference RMSD requires one exact alignment pair"
                )
            self._assert_alignment_identity(
                alignment,
                subjects[0],
                references[0],
            )
            self._assert_alignment_method(alignment)
            observations = (
                self._observation(
                    alignment,
                    pairing_mode="fixed_reference",
                ),
            )
        elif self._pairing_mode == "per_subject_counterpart":
            if set(inputs) != {
                "alignments",
                "subjects",
                "references",
                "pairing",
            }:
                raise ValueError(
                    "paired RMSD requires alignments, subjects, references, "
                    "and pairing"
                )
            subjects = self._candidates(inputs["subjects"], role="subjects")
            references = self._candidates(
                inputs["references"],
                role="references",
            )
            pairs = self._pairing(
                inputs["pairing"],
                subjects=subjects,
                references=references,
            )
            collection = inputs["alignments"]
            if (
                type(collection) is not StructureAlignmentEvidenceCollection
                or len(collection.alignments) != len(pairs)
            ):
                raise ValueError(
                    "paired RMSD requires one alignment for every pairing"
                )
            by_pair = {
                (
                    alignment.subject.candidate_id,
                    alignment.reference.candidate_id,
                ): alignment
                for alignment in collection.alignments
            }
            observations_list: list[ScoreObservation] = []
            for subject, reference in pairs:
                key = (
                    subject[0].candidate_id,
                    reference[0].candidate_id,
                )
                alignment = by_pair.get(key)
                if alignment is None:
                    raise ValueError(
                        "alignment collection does not match the pairing source"
                    )
                self._assert_alignment_identity(
                    alignment,
                    subject,
                    reference,
                )
                self._assert_alignment_method(alignment)
                observations_list.append(
                    self._observation(
                        alignment,
                        pairing_mode="per_subject_counterpart",
                    )
                )
            if len(by_pair) != len(pairs):
                raise ValueError(
                    "alignment collection contains undeclared pairs"
                )
            observations = tuple(observations_list)
        else:
            raise RuntimeError("RMSD Binding pairing mode is not declared")
        return {
            "scores": ScoreCollection(
                collection_id="structure-comparison-rmsd",
                entries=list(observations),
            )
        }
