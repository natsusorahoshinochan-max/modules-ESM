"""Direct implementations for exact role-labelled structure comparison."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from tmtools import tm_align

from core import OperationCall, OperationContext, ResolvedProducedObservation
from datatypes import (
    Candidate,
    CandidateCollection,
    PairwiseCandidateMapping,
    PairwiseObservationContext,
    PairwiseParticipant,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
)
from .alignment import (
    align_structures,
    count_structure_ca_residues,
)

from .domain import (
    AlignmentAtomCorrespondence,
    StructureAlignmentEvidence,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
)


class StructureComparisonImplementation:
    """Dispatch the package's five Node Types through one implementation."""

    def __init__(
        self,
        context: OperationContext,
        operation: str,
        pairing_mode: str | None = None,
    ) -> None:
        self._run_resources = context.resources
        self._method = context.method
        self._produced_observations = context.produced_observations
        self._operation = operation
        self._pairing_mode = pairing_mode

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "structure comparison Nodes do not accept parameters"
            )
        if self._operation == "align_single":
            return self._align_single(call)
        if self._operation == "align_pairwise":
            if self._pairing_mode == "fixed_reference":
                return self._align_fixed_reference(call)
            return self._align_pairwise(call)
        if self._operation == "rmsd":
            return self._observe_rmsd(call)
        if self._operation == "tm_score":
            return self._observe_single_tm_score(call)
        if self._operation == "batch_tm_score":
            return self._observe_batch_tm_score(call)
        raise RuntimeError("unknown structure comparison operation")

    def _produced_observation(self) -> ResolvedProducedObservation:
        matches = tuple(
            observation
            for observation in self._produced_observations
            if observation.output_port == "scores"
        )
        if len(matches) != 1:
            raise RuntimeError(
                "comparison score Binding must resolve one exact Observation"
            )
        return matches[0]

    def _candidates(
        self,
        call: OperationCall,
        *,
        port_name: str,
        role: str,
    ) -> tuple[tuple[Candidate, str], ...]:
        value = call.inputs[port_name]
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
        digests = {
            candidate.candidate_id: candidate.content_digest
            for candidate in call.input_content_digests[
                port_name
            ].candidate_data
        }
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
            try:
                digest = digests[candidate.candidate_id]
            except KeyError as error:
                raise ValueError(
                    f"{role} lacks exact Candidate content identity"
                ) from error
            result.append((candidate, digest))
        if set(digests) != ids:
            raise ValueError(
                f"{role} content identities contradict its Candidates"
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
            method=self._method,
        )

    def _align_single(
        self,
        call: OperationCall,
    ) -> dict[str, Any]:
        inputs = call.inputs
        if set(inputs) != {"subjects", "references"}:
            raise ValueError(
                "single alignment requires subjects and references"
            )
        subjects = self._candidates(
            call,
            port_name="subjects",
            role="subjects",
        )
        references = self._candidates(
            call,
            port_name="references",
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
        call: OperationCall,
    ) -> dict[str, Any]:
        inputs = call.inputs
        if set(inputs) != {"subjects", "references", "pairing"}:
            raise ValueError(
                "pairwise alignment requires subjects, references, and pairing"
            )
        subjects = self._candidates(
            call,
            port_name="subjects",
            role="subjects",
        )
        references = self._candidates(
            call,
            port_name="references",
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
        return {"alignments": alignments}

    def _align_fixed_reference(
        self,
        call: OperationCall,
    ) -> dict[str, Any]:
        inputs = call.inputs
        if set(inputs) != {"subjects", "references"}:
            raise ValueError(
                "fixed-reference alignment requires subjects and references"
            )
        subjects = self._candidates(
            call,
            port_name="subjects",
            role="subjects",
        )
        references = self._candidates(
            call,
            port_name="references",
            role="references",
        )
        if len(references) != 1:
            raise ValueError(
                "fixed-reference alignment requires one exact reference"
            )
        reference, reference_digest = references[0]
        if any(
            subject.candidate_id == reference.candidate_id
            for subject, _ in subjects
        ):
            raise ValueError(
                "subject and reference Candidate identities must be disjoint"
            )
        alignments = tuple(
            self._alignment(
                subject=subject,
                subject_digest=subject_digest,
                reference=reference,
                reference_digest=reference_digest,
                engine_role=f"fixed_reference_alignment_{index}",
            )
            for index, (subject, subject_digest) in enumerate(subjects)
        )
        return {"alignments": alignments}

    @staticmethod
    def _rmsd(alignment: StructureAlignmentEvidence) -> float:
        count = alignment.normalization.aligned_atom_count
        if count != len(alignment.correspondence) or count < 1:
            raise ValueError("RMSD requires complete non-empty correspondence")
        value = float(alignment.rmsd)
        if not math.isfinite(value):
            raise ValueError("RMSD must be finite")
        return value

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
        if (
            alignment.normalization.subject_residue_count
            != count_structure_ca_residues(subject[0].data)
            or alignment.normalization.reference_residue_count
            != count_structure_ca_residues(reference[0].data)
        ):
            raise ValueError(
                "alignment normalization conflicts with exact Candidate content"
            )

    def _observation(
        self,
        alignment: StructureAlignmentEvidence,
    ) -> ScoreObservation:
        produced = self._produced_observation()
        profile = produced.context_profile
        with self._run_resources.engine_invocation(
            engine_role="rmsd_observation",
        ):
            value = self._rmsd(alignment)
        return ScoreObservation(
            candidate_id=alignment.subject.candidate_id,
            metric=produced.metric,
            method=self._method,
            context=PairwiseObservationContext(
                subject=alignment.subject,
                reference=alignment.reference,
                pairing_mode=str(profile["pairing_mode"]),
                normalization=str(profile["normalization"]),
            ),
            value=value,
            source_partition=produced.output_partition,
        )

    def _observe_rmsd(
        self,
        call: OperationCall,
    ) -> dict[str, Any]:
        inputs = call.inputs
        if self._pairing_mode == "fixed_reference":
            if set(inputs) != {"alignment", "subjects", "references"}:
                raise ValueError(
                    "fixed-reference RMSD requires alignment, subjects, and "
                    "references"
                )
            subjects = self._candidates(
                call,
                port_name="subjects",
                role="subjects",
            )
            references = self._candidates(
                call,
                port_name="references",
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
            observations = (self._observation(alignment),)
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
            subjects = self._candidates(
                call,
                port_name="subjects",
                role="subjects",
            )
            references = self._candidates(
                call,
                port_name="references",
                role="references",
            )
            pairs = self._pairing(
                inputs["pairing"],
                subjects=subjects,
                references=references,
            )
            alignments = inputs["alignments"]
            if (
                type(alignments) is not tuple
                or len(alignments) != len(pairs)
                or any(
                    type(alignment) is not StructureAlignmentEvidence
                    for alignment in alignments
                )
            ):
                raise ValueError(
                    "paired RMSD requires one alignment for every pairing"
                )
            by_pair = self._alignment_index(alignments)
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
                observations_list.append(
                    self._observation(alignment)
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

    @staticmethod
    def _validate_tm_score_evidence(
        alignment: StructureAlignmentEvidence,
    ) -> None:
        count = alignment.normalization.aligned_atom_count
        reference_count = alignment.normalization.reference_residue_count
        subject_count = alignment.normalization.subject_residue_count
        if (
            count != len(alignment.correspondence)
            or count < 1
            or reference_count < count
            or subject_count < count
        ):
            raise ValueError(
                "TM-score requires complete non-empty alignment evidence"
            )
        if any(
            not math.isfinite(float(coordinate))
            for item in alignment.correspondence
            for coordinate in (
                *item.reference_coordinate,
                *item.subject_coordinate,
            )
        ):
            raise ValueError("TM-score coordinates must be finite")

    def _preflight_tm_alignment(
        self,
        alignment: StructureAlignmentEvidence,
        subject: tuple[Candidate, str],
        reference: tuple[Candidate, str],
    ) -> None:
        self._assert_alignment_identity(alignment, subject, reference)
        self._validate_tm_score_evidence(alignment)

    def _tm_score(self, alignment: StructureAlignmentEvidence) -> float:
        self._validate_tm_score_evidence(alignment)
        count = alignment.normalization.aligned_atom_count
        reference_count = alignment.normalization.reference_residue_count
        subject_count = alignment.normalization.subject_residue_count
        reference_coordinates = np.zeros(
            (reference_count, 3),
            dtype=np.float64,
        )
        subject_coordinates = np.zeros(
            (subject_count, 3),
            dtype=np.float64,
        )
        reference_coordinates[:count] = np.asarray(
            [
                item.reference_coordinate
                for item in alignment.correspondence
            ],
            dtype=np.float64,
        )
        subject_coordinates[:count] = np.asarray(
            [
                item.subject_coordinate
                for item in alignment.correspondence
            ],
            dtype=np.float64,
        )
        if (
            not np.isfinite(reference_coordinates[:count]).all()
            or not np.isfinite(subject_coordinates[:count]).all()
        ):
            raise ValueError("TM-score coordinates must be finite")
        fixed_alignment = (
            (
                "A" * count
                + "A" * (reference_count - count)
                + "-" * (subject_count - count)
            ),
            (
                "A" * count
                + "-" * (reference_count - count)
                + "A" * (subject_count - count)
            ),
        )
        with self._run_resources.engine_invocation(
            engine_role="tm_score_optimization",
        ):
            optimized = tm_align(
                reference_coordinates,
                subject_coordinates,
                "A" * reference_count,
                "A" * subject_count,
                fixed_alignment,
            )
        transformed_reference = (
            reference_coordinates[:count]
            @ np.asarray(optimized.u, dtype=np.float64).T
            + np.asarray(optimized.t, dtype=np.float64)
        )
        optimized_distances = np.linalg.norm(
            subject_coordinates[:count] - transformed_reference,
            axis=1,
        )
        if not np.isfinite(optimized_distances).all():
            raise ValueError("TM-score optimization returned non-finite evidence")
        d0 = (
            1.24 * (reference_count - 15) ** (1.0 / 3.0) - 1.8
            if reference_count > 15
            else 0.5
        )
        d0 = max(0.5, d0)
        value = math.fsum(
            1.0 / (1.0 + (float(distance) / d0) ** 2)
            for distance in optimized_distances
        ) / reference_count
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(
                "TM-score must be finite within its canonical range"
            )
        return value

    def _tm_observation(
        self,
        alignment: StructureAlignmentEvidence,
        evidence_content_digest: str,
    ) -> ScoreObservation:
        produced = self._produced_observation()
        profile = produced.context_profile
        value = self._tm_score(alignment)
        return ScoreObservation(
            candidate_id=alignment.subject.candidate_id,
            metric=produced.metric,
            method=self._method,
            context=PairwiseObservationContext(
                subject=alignment.subject,
                reference=alignment.reference,
                pairing_mode=str(profile["pairing_mode"]),
                normalization=str(profile["normalization"]),
                evidence_content_digest=evidence_content_digest,
                evidence_method=alignment.method,
                normalization_length=(
                    alignment.normalization.reference_residue_count
                ),
                aligned_atom_count=(
                    alignment.normalization.aligned_atom_count
                ),
            ),
            value=value,
            source_partition=produced.output_partition,
        )

    def _observe_single_tm_score(
        self,
        call: OperationCall,
    ) -> dict[str, Any]:
        inputs = call.inputs
        if set(inputs) != {"alignment", "subjects", "references"}:
            raise ValueError(
                "single TM-score requires alignment, subjects, and references"
            )
        subjects = self._candidates(
            call,
            port_name="subjects",
            role="subjects",
        )
        references = self._candidates(
            call,
            port_name="references",
            role="references",
        )
        alignment = inputs["alignment"]
        if (
            type(alignment) is not StructureAlignmentEvidence
            or len(subjects) != 1
            or len(references) != 1
        ):
            raise ValueError(
                "single TM-score requires one exact alignment pair"
            )
        self._preflight_tm_alignment(
            alignment,
            subjects[0],
            references[0],
        )
        digest_record = call.input_content_digests.get("alignment")
        if (
            digest_record is None
            or digest_record.port_type_id
            != "structure_comparison.alignment"
            or len(digest_record.value_content_digests) != 1
        ):
            raise ValueError(
                "single TM-score lacks exact alignment content identity"
            )
        observation = self._tm_observation(
            alignment,
            digest_record.value_content_digests[0],
        )
        return {
            "scores": ScoreCollection(
                collection_id="structure-comparison-tm-score-single",
                entries=[observation],
            )
        }

    @staticmethod
    def _alignment_index(
        alignments: tuple[StructureAlignmentEvidence, ...],
    ) -> dict[tuple[str, str], StructureAlignmentEvidence]:
        index: dict[tuple[str, str], StructureAlignmentEvidence] = {}
        for alignment in alignments:
            key = (
                alignment.subject.candidate_id,
                alignment.reference.candidate_id,
            )
            if key in index:
                raise ValueError(
                    "alignment inputs contain a duplicate exact pair"
                )
            index[key] = alignment
        return index

    @staticmethod
    def _digested_alignment_index(
        call: OperationCall,
    ) -> dict[tuple[str, str], tuple[StructureAlignmentEvidence, str]]:
        alignments = call.inputs["alignments"]
        digest_record = call.input_content_digests.get("alignments")
        if (
            type(alignments) is not tuple
            or not alignments
            or any(
                type(alignment) is not StructureAlignmentEvidence
                for alignment in alignments
            )
            or digest_record is None
            or digest_record.port_type_id
            != "structure_comparison.alignment"
            or len(digest_record.value_content_digests) != len(alignments)
        ):
            raise ValueError(
                "batch TM-score lacks exact per-alignment content identity"
            )
        index: dict[
            tuple[str, str],
            tuple[StructureAlignmentEvidence, str],
        ] = {}
        for alignment, content_digest in zip(
            alignments,
            digest_record.value_content_digests,
            strict=True,
        ):
            key = (
                alignment.subject.candidate_id,
                alignment.reference.candidate_id,
            )
            if key in index:
                raise ValueError(
                    "alignment inputs contain a duplicate exact pair"
                )
            index[key] = (alignment, content_digest)
        return index

    def _observe_batch_tm_score(
        self,
        call: OperationCall,
    ) -> dict[str, Any]:
        inputs = call.inputs
        if self._pairing_mode == "per_subject_counterpart":
            if set(inputs) != {
                "alignments",
                "subjects",
                "references",
                "pairing",
            }:
                raise ValueError(
                    "paired batch TM-score requires alignments, subjects, "
                    "references, and pairing"
                )
            subjects = self._candidates(
                call,
                port_name="subjects",
                role="subjects",
            )
            references = self._candidates(
                call,
                port_name="references",
                role="references",
            )
            pairs = self._pairing(
                inputs["pairing"],
                subjects=subjects,
                references=references,
            )
            index = self._digested_alignment_index(call)
            if len(index) != len(pairs):
                raise ValueError(
                    "paired batch TM-score requires complete one-to-one "
                    "alignment evidence"
                )
            expected_keys = {
                (
                    subject[0].candidate_id,
                    reference[0].candidate_id,
                )
                for subject, reference in pairs
            }
            if set(index) != expected_keys:
                raise ValueError(
                    "alignment inputs conflict with the pairing source"
                )
            resolved_alignments: list[
                tuple[StructureAlignmentEvidence, str]
            ] = []
            for subject, reference in pairs:
                alignment, evidence_digest = index[
                    (
                        subject[0].candidate_id,
                        reference[0].candidate_id,
                    )
                ]
                self._preflight_tm_alignment(
                    alignment,
                    subject,
                    reference,
                )
                resolved_alignments.append((alignment, evidence_digest))
            observations = [
                self._tm_observation(alignment, evidence_digest)
                for alignment, evidence_digest in resolved_alignments
            ]
        elif self._pairing_mode == "fixed_reference":
            if set(inputs) != {"alignments", "subjects", "references"}:
                raise ValueError(
                    "fixed-reference batch TM-score requires alignments, "
                    "subjects, and references"
                )
            subjects = self._candidates(
                call,
                port_name="subjects",
                role="subjects",
            )
            references = self._candidates(
                call,
                port_name="references",
                role="references",
            )
            index = self._digested_alignment_index(call)
            if len(references) != 1 or len(index) != len(subjects):
                raise ValueError(
                    "fixed-reference batch TM-score requires complete "
                    "many-to-one alignment evidence"
                )
            reference = references[0]
            expected_keys = {
                (
                    subject[0].candidate_id,
                    reference[0].candidate_id,
                )
                for subject in subjects
            }
            if set(index) != expected_keys:
                raise ValueError(
                    "fixed-reference alignments conflict with exact sources"
                )
            resolved_alignments = []
            for subject in subjects:
                alignment, evidence_digest = index[
                    (
                        subject[0].candidate_id,
                        reference[0].candidate_id,
                    )
                ]
                self._preflight_tm_alignment(
                    alignment,
                    subject,
                    reference,
                )
                resolved_alignments.append((alignment, evidence_digest))
            observations = [
                self._tm_observation(alignment, evidence_digest)
                for alignment, evidence_digest in resolved_alignments
            ]
        else:
            raise RuntimeError(
                "batch TM-score Binding pairing mode is not declared"
            )
        return {
            "scores": ScoreCollection(
                collection_id=(
                    "structure-comparison-tm-score-"
                    f"{self._pairing_mode}"
                ),
                entries=observations,
            )
        }
