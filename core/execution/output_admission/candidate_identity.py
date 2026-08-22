"""Candidate identity, lineage, pairing, and Score normalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from core.catalog.port_contract import (
    PortValueError,
    _candidate_data_reference_to_canonical,
    _residue_axis_reference_to_canonical,
    canonical_sha256,
    observation_context_canonical,
)
from core.operation import (
    AdmittedPort,
    CandidateMetadataIdentity,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
)
from core.execution.output_admission.identity import (
    _FreshOutputIdentityEncoder,
)
from core.scoring.observation_plan import ObservationPropagationPlan
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    validate_candidate_lineage_graph,
    validate_candidate_parent_ids,
)
from datatypes.observation import (
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


_RUNTIME_METADATA_KEYS = frozenset(
    {
        "run",
        "run_id",
        "node",
        "node_id",
        "timestamp",
        "created_at",
        "updated_at",
        "credential",
        "credentials",
        "private_path",
        "runtime_path",
        "presentation",
        "performance",
    }
)


def _candidate_values(value: Any) -> tuple[Candidate, ...]:
    if type(value) is Candidate:
        return (value,)
    if type(value) is CandidateCollection:
        return tuple(value.items)
    if isinstance(value, (list, tuple)):
        return tuple(
            candidate
            for item in value
            for candidate in _candidate_values(item)
        )
    return ()


@dataclass(frozen=True, slots=True)
class _CandidateOutput:
    candidate: Candidate
    output_port: str
    value_index: int
    sample_index: int


@dataclass(frozen=True, slots=True)
class _NormalizedCandidateOutputs:
    values: Mapping[str, tuple[Any, ...]]
    candidate_data: Mapping[str, CandidateDataReference]


def _candidate_data_type_id(value: object) -> str | None:
    return {
        ProteinSequence: "protein.sequence",
        ProteinStructure: "protein.structure",
    }.get(type(value))


def _normalized_score(
    score: ScoreObservation,
    *,
    require_exact_input_subject: Callable[
        [CandidateDataReference], CandidateDataReference
    ],
) -> ScoreObservation:
    if type(score) is not ScoreObservation:
        raise PortValueError(
            "Score Collection contains an unsupported entry"
        )
    subject = require_exact_input_subject(score.subject)
    context = score.context
    if isinstance(context, PairwiseObservationContext):
        if (
            context.subject.candidate_id != score.subject.candidate_id
            or context.subject.content_digest != score.subject.content_digest
        ):
            raise PortValueError(
                "Pairwise Score Context subject conflicts with exact subject"
            )
        context = replace(
            context,
            subject=replace(
                context.subject,
                candidate=require_exact_input_subject(
                    context.subject.candidate
                ),
            ),
            reference=replace(
                context.reference,
                candidate=require_exact_input_subject(
                    context.reference.candidate
                ),
            ),
        )
    return replace(score, subject=subject, context=context)


def _propagated_candidate_reference_index(
    *,
    observation_propagation: ObservationPropagationPlan,
    inputs: Mapping[str, AdmittedPort],
) -> tuple[str, Mapping[str, CandidateDataReference]]:
    output_port = observation_propagation.output_port
    by_candidate_id: dict[str, CandidateDataReference] = {}
    for input_port in observation_propagation.input_ports:
        record = inputs.get(input_port)
        for reference in record.candidate_data if record is not None else ():
            previous = by_candidate_id.get(reference.candidate_id)
            if previous is not None and previous != reference:
                raise PortValueError(
                    "Observation propagation inputs contain conflicting "
                    "propagated Candidate references"
                )
            by_candidate_id[reference.candidate_id] = reference
    return output_port, MappingProxyType(by_candidate_id)


def _score_collection_id(
    *,
    result_identity: str,
    output_port: str,
    value_slot: int,
    entries: tuple[ScoreObservation, ...],
) -> str:
    return "scores-" + canonical_sha256(
        {
            "schema_namespace": "protein-workbench-score-collection/v2",
            "producer_result_identity": result_identity,
            "output_port": output_port,
            "value_slot": value_slot,
            "scores": [
                {
                    "subject": _candidate_data_reference_to_canonical(
                        score.subject
                    ),
                    "metric": {
                        "contract_kind": score.metric.contract_kind,
                        "contract_id": score.metric.contract_id,
                        "contract_version": score.metric.contract_version,
                        "contract_digest": score.metric.contract_digest,
                    },
                    "method": {
                        "contract_kind": score.method.contract_kind,
                        "contract_id": score.method.contract_id,
                        "contract_version": score.method.contract_version,
                        "contract_digest": score.method.contract_digest,
                    },
                    "context": observation_context_canonical(score.context),
                    "residue_axis": (
                        None
                        if score.residue_axis is None
                        else _residue_axis_reference_to_canonical(
                            score.residue_axis
                        )
                    ),
                    "source_partition": score.source_partition,
                    "value": score.value,
                }
                for score in entries
            ],
        }
    ).removeprefix("sha256:")


def _normalize_candidate_outputs(
    *,
    result_identity: str,
    inputs: Mapping[str, AdmittedPort],
    outputs: Mapping[str, tuple[Any, ...]],
    candidate_data_port_types: Mapping[str, Any],
    identity_encoder: _FreshOutputIdentityEncoder,
    candidate_metadata: tuple[CandidateMetadataIdentity, ...] = (),
    observation_propagation: ObservationPropagationPlan | None = None,
) -> _NormalizedCandidateOutputs:
    """Normalize producer-local identities before nominal Port admission."""
    input_candidates = {
        candidate.candidate_id: candidate
        for admitted in inputs.values()
        for candidate in _candidate_values(admitted.value)
    }
    input_candidate_references = {
        reference.candidate_id: reference
        for admitted in inputs.values()
        for reference in admitted.candidate_data
    }
    input_pairing_references: dict[str, CandidateDataReference] = {}
    for admitted in inputs.values():
        value = admitted.value
        if type(value) is not PairwiseCandidateMapping:
            continue
        for entry in value.entries:
            for reference in (entry.subject, entry.reference):
                known = input_pairing_references.get(reference.candidate_id)
                if known is not None and known != reference:
                    raise PortValueError(
                        "Candidate pairing inputs contradict one exact "
                        "Candidate reference"
                    )
                input_pairing_references[reference.candidate_id] = reference
    propagated_output_port: str | None = None
    propagated_references: Mapping[str, CandidateDataReference] = (
        MappingProxyType({})
    )
    if observation_propagation is not None:
        propagated_output_port, propagated_references = (
            _propagated_candidate_reference_index(
                observation_propagation=observation_propagation,
                inputs=inputs,
            )
        )
    normalized_ids: dict[str, str] = {}
    normalized_candidates: dict[str, Candidate] = {}
    normalized_candidate_digests: dict[str, str] = {}
    output_candidates: dict[str, _CandidateOutput] = {}
    metadata_by_candidate: dict[str, dict[str, str]] = {}
    for metadata in candidate_metadata:
        fields = metadata_by_candidate.setdefault(metadata.candidate_id, {})
        if metadata.field_name in fields:
            raise PortValueError(
                "Output identity intents assign duplicate Candidate metadata"
            )
        fields[metadata.field_name] = metadata.value

    for output_port in sorted(outputs):
        for value_index, value in enumerate(outputs[output_port]):
            for sample_index, candidate in enumerate(
                _candidate_values(value)
            ):
                raw_candidate_id = candidate.candidate_id
                if raw_candidate_id in output_candidates:
                    raise PortValueError(
                        "Candidate output reuses one producer identity"
                    )
                output_candidates[raw_candidate_id] = _CandidateOutput(
                    candidate=candidate,
                    output_port=output_port,
                    value_index=value_index,
                    sample_index=sample_index,
                )

    if set(metadata_by_candidate) - set(output_candidates):
        raise PortValueError(
            "Output identity intent names an unknown Candidate identity"
        )

    try:
        for output in output_candidates.values():
            validate_candidate_parent_ids(
                output.candidate,
                subject="Candidate output lineage",
            )
        validate_candidate_lineage_graph(
            tuple(
                output.candidate for output in output_candidates.values()
            ),
            subject="Candidate output lineage",
        )
    except ValueError as error:
        raise PortValueError(str(error)) from error

    def resolve_candidate(raw_candidate_id: str) -> None:
        if raw_candidate_id in normalized_candidates:
            return
        output = output_candidates[raw_candidate_id]
        candidate = output.candidate
        input_candidate = input_candidates.get(raw_candidate_id)
        if input_candidate is not None:
            if raw_candidate_id in metadata_by_candidate:
                raise PortValueError(
                    "Output identity intent cannot modify a pass-through "
                    "Candidate"
                )
            if candidate != input_candidate:
                raise PortValueError(
                    "Candidate pass-through changed exact input identity, "
                    "lineage, content, or metadata"
                )
            normalized_ids[raw_candidate_id] = raw_candidate_id
            normalized_candidates[raw_candidate_id] = Candidate(
                candidate_id=candidate.candidate_id,
                data=candidate.data,
                parent_ids=list(candidate.parent_ids),
                metadata=dict(candidate.metadata),
            )
            reference = input_candidate_references.get(raw_candidate_id)
            if reference is None:
                raise PortValueError(
                    "Candidate pass-through lacks admitted content identity"
                )
            normalized_candidate_digests[raw_candidate_id] = (
                reference.content_digest
            )
            return

        parents: list[str] = []
        normalized_parent_ids: set[str] = set()
        for parent_id in candidate.parent_ids:
            if parent_id in input_candidates:
                normalized_parent_id = parent_id
            else:
                if parent_id not in output_candidates:
                    raise PortValueError(
                        "Candidate parent identity is not a resolved input "
                        "or output Candidate"
                    )
                resolve_candidate(parent_id)
                normalized_parent_id = normalized_ids[parent_id]
            if normalized_parent_id in normalized_parent_ids:
                raise PortValueError(
                    "Candidate parent identities normalize to one duplicate "
                    "parent identity"
                )
            normalized_parent_ids.add(normalized_parent_id)
            parents.append(normalized_parent_id)
        type_id = _candidate_data_type_id(candidate.data)
        if type_id is None:
            raise PortValueError(
                "Candidate data has no registered content identity"
            )
        try:
            candidate_data_port_type = candidate_data_port_types[type_id]
        except KeyError as error:
            raise PortValueError(
                f"Execution Plan lacks Candidate data Port Type {type_id!r}"
            ) from error
        content_digest = identity_encoder.encode_value(
            port_type=candidate_data_port_type,
            value=candidate.data,
        ).content_digest
        sample_slot = f"{output.value_index}:{output.sample_index}"
        candidate_identity = canonical_sha256(
            {
                "schema_namespace": "protein-workbench-candidate/v2",
                "producer_result_identity": result_identity,
                "output_port": output.output_port,
                "sample_slot": sample_slot,
                "parent_candidate_identities": parents,
                "content_digest": content_digest,
            }
        )
        normalized_id = "candidate-" + candidate_identity.removeprefix(
            "sha256:"
        )
        normalized_ids[raw_candidate_id] = normalized_id
        resolved_metadata = metadata_by_candidate.get(raw_candidate_id, {})
        if set(resolved_metadata) & set(candidate.metadata):
            raise PortValueError(
                "Operation output precomputed identity-owned Candidate metadata"
            )
        normalized_candidates[raw_candidate_id] = Candidate(
            candidate_id=normalized_id,
            data=candidate.data,
            parent_ids=parents,
            metadata={
                **{
                    key: item
                    for key, item in candidate.metadata.items()
                    if key not in _RUNTIME_METADATA_KEYS
                },
                **resolved_metadata,
                "producer_result_identity": result_identity,
                "output_port": output.output_port,
                "sample_slot": sample_slot,
                "content_digest": content_digest,
            },
        )
        normalized_candidate_digests[raw_candidate_id] = content_digest

    for raw_candidate_id in output_candidates:
        resolve_candidate(raw_candidate_id)

    def exact_input_candidate_facts(
        candidate_id: str,
    ) -> tuple[Candidate, CandidateDataReference]:
        candidate = input_candidates.get(candidate_id)
        if candidate is None:
            if candidate_id in output_candidates:
                raise PortValueError(
                    "Score subject cannot reference a same-operation output "
                    "Candidate before admission"
                )
            raise PortValueError(
                "Score subject names an unknown input Candidate identity"
            )
        reference = input_candidate_references.get(candidate_id)
        if reference is None:
            raise PortValueError(
                "Score subject Candidate lacks admitted content identity"
            )
        return candidate, reference

    def require_exact_input_subject(
        subject: CandidateDataReference,
    ) -> CandidateDataReference:
        _, expected = exact_input_candidate_facts(subject.candidate_id)
        if subject != expected:
            raise PortValueError(
                "Score subject conflicts with exact Candidate content identity"
            )
        return expected

    def require_exact_input_candidate_reference(
        reference: CandidateDataReference,
    ) -> CandidateDataReference:
        candidate = input_candidates.get(reference.candidate_id)
        if candidate is None:
            expected = input_pairing_references.get(reference.candidate_id)
            if expected is None:
                raise PortValueError(
                    "Candidate pairing names an unknown input Candidate reference"
                )
            if reference != expected:
                raise PortValueError(
                    "Candidate pairing conflicts with an admitted input pairing"
                )
            return expected
        expected = input_candidate_references.get(reference.candidate_id)
        if expected is None:
            raise PortValueError(
                "Candidate pairing input lacks admitted content identity"
            )
        if reference != expected:
            raise PortValueError(
                "Candidate pairing conflicts with exact input Candidate "
                "reference"
            )
        return expected

    def require_exact_propagated_subject(
        subject: CandidateDataReference,
    ) -> CandidateDataReference:
        expected = propagated_references.get(subject.candidate_id)
        if expected is None:
            raise PortValueError(
                "Observation propagation output names an unknown propagated "
                "Candidate reference"
            )
        if expected != subject:
            raise PortValueError(
                "Observation propagation output conflicts with an admitted "
                "propagated Candidate reference"
            )
        return expected

    def normalized_output_candidate_reference(
        raw_candidate_id: str,
    ) -> CandidateDataReference:
        candidate = normalized_candidates[raw_candidate_id]
        data_type_id = _candidate_data_type_id(candidate.data)
        if data_type_id is None:
            raise PortValueError(
                "Candidate pairing output has no canonical data type identity"
            )
        return CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id=data_type_id,
            content_digest=normalized_candidate_digests[raw_candidate_id],
        )

    def project_pairing_intent(
        value: CandidatePairingIntent,
    ) -> PairwiseCandidateMapping:
        subject_counterparts: dict[str, str] = {}
        reference_subjects: dict[str, str] = {}
        exact_pairs: set[tuple[str, str]] = set()
        entries: list[PairwiseCandidateMatch] = []
        for entry in value.entries:
            if type(entry) is not CandidatePairingIntentEntry:
                raise PortValueError(
                    "Candidate pairing intent contains an unsupported entry"
                )
            raw_pair = (
                entry.subject_candidate_id,
                entry.reference_candidate_id,
            )
            if raw_pair in exact_pairs:
                raise PortValueError(
                    "Candidate pairing intent contains a duplicate exact pair"
                )
            exact_pairs.add(raw_pair)
            try:
                subject = normalized_output_candidate_reference(
                    entry.subject_candidate_id
                )
                reference = normalized_output_candidate_reference(
                    entry.reference_candidate_id
                )
            except KeyError as error:
                raise PortValueError(
                    "Candidate pairing intent names an unknown Candidate identity"
                ) from error
            known_reference = subject_counterparts.get(
                entry.subject_candidate_id
            )
            known_subject = reference_subjects.get(
                entry.reference_candidate_id
            )
            if (
                (
                    known_reference is not None
                    and known_reference != entry.reference_candidate_id
                )
                or (
                    known_subject is not None
                    and known_subject != entry.subject_candidate_id
                )
                or entry.subject_candidate_id == entry.reference_candidate_id
            ):
                raise PortValueError(
                    "Candidate pairing intent declares a conflicting counterpart"
                )
            subject_counterparts[entry.subject_candidate_id] = (
                entry.reference_candidate_id
            )
            reference_subjects[entry.reference_candidate_id] = (
                entry.subject_candidate_id
            )
            entries.append(
                PairwiseCandidateMatch(
                    subject=subject,
                    reference=reference,
                )
            )
        return PairwiseCandidateMapping(entries)

    def normalize_value(
        output_port: str,
        value_index: int,
        value: Any,
    ) -> Any:
        if type(value) is Candidate:
            return normalized_candidates[value.candidate_id]
        if type(value) is CandidateCollection:
            items = tuple(
                normalized_candidates[candidate.candidate_id]
                for candidate in value.items
            )
            collection_id = "collection-" + canonical_sha256(
                {
                    "schema_namespace": (
                        "protein-workbench-candidate-collection/v2"
                    ),
                    "producer_result_identity": result_identity,
                    "output_port": output_port,
                    "value_slot": value_index,
                    "candidate_identities": [
                        candidate.candidate_id for candidate in items
                    ],
                }
            ).removeprefix("sha256:")
            return CandidateCollection(
                collection_id=collection_id,
                item_type=value.item_type,
                items=list(items),
            )
        if type(value) is PairwiseCandidateMapping:
            return PairwiseCandidateMapping(
                entries=[
                    PairwiseCandidateMatch(
                        subject=require_exact_input_candidate_reference(
                            entry.subject
                        ),
                        reference=require_exact_input_candidate_reference(
                            entry.reference
                        ),
                    )
                    for entry in value.entries
                ]
            )
        if type(value) is CandidatePairingIntent:
            return project_pairing_intent(value)
        if type(value) is ScoreCollection:
            require_subject = (
                require_exact_propagated_subject
                if output_port == propagated_output_port
                else require_exact_input_subject
            )
            entries = tuple(
                _normalized_score(
                    score,
                    require_exact_input_subject=require_subject,
                )
                for score in value.entries
            )
            return ScoreCollection(
                collection_id=_score_collection_id(
                    result_identity=result_identity,
                    output_port=output_port,
                    value_slot=value_index,
                    entries=entries,
                ),
                entries=list(entries),
            )
        return value

    normalized_outputs: dict[str, tuple[Any, ...]] = {}
    for output_port, values in outputs.items():
        normalized_outputs[output_port] = tuple(
            normalize_value(output_port, index, value)
            for index, value in enumerate(values)
        )
    candidate_data: dict[str, CandidateDataReference] = {}
    for raw_candidate_id, candidate in normalized_candidates.items():
        data_type_id = _candidate_data_type_id(candidate.data)
        if data_type_id is None:
            raise PortValueError(
                "Candidate data has no registered content identity"
            )
        candidate_data[candidate.candidate_id] = CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id=data_type_id,
            content_digest=normalized_candidate_digests[raw_candidate_id],
        )
    return _NormalizedCandidateOutputs(
        values=MappingProxyType(normalized_outputs),
        candidate_data=MappingProxyType(candidate_data),
    )
