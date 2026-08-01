"""Pure reconstruction and canonical admission of scientific Port values."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
import hashlib
from types import MappingProxyType
from typing import Any

from core.operation import (
    CandidateDataDigest,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
)
from core.port_types import PortValueError, canonical_sha256
from datatypes import (
    Candidate,
    CandidateCollection,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    ScoreCollection,
    ScoreObservation,
)


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


@dataclass(frozen=True, slots=True)
class AdmittedValue:
    """One canonical codec snapshot retained after boundary admission."""

    canonical_bytes: bytes
    content_digest: str
    runtime_value: Any
    candidate_data: tuple[CandidateDataDigest, ...] = ()


@dataclass(frozen=True, slots=True)
class AdmittedPortValues:
    """All admitted values for one exact output Port."""

    port_type: Mapping[str, Any]
    multiplicity: str
    values: tuple[AdmittedValue, ...]
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "port_type",
            MappingProxyType(dict(self.port_type)),
        )
        object.__setattr__(self, "values", tuple(self.values))

    @property
    def runtime_values(self) -> tuple[Any, ...]:
        return tuple(value.runtime_value for value in self.values)

    def __bool__(self) -> bool:
        return bool(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.runtime_values)

    def __getitem__(self, index: int) -> Any:
        return self.values[index].runtime_value


def _admitted_from_canonical_bytes(
    *,
    port_type: Any,
    canonical_bytes: bytes,
    candidate_data: Callable[[Any], tuple[CandidateDataDigest, ...]],
) -> AdmittedValue:
    runtime_value = port_type.decode(canonical_bytes)
    return AdmittedValue(
        canonical_bytes=canonical_bytes,
        content_digest=(
            "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
        ),
        runtime_value=runtime_value,
        candidate_data=candidate_data(runtime_value),
    )


def admitted_port_values(
    *,
    port_type: Any,
    multiplicity: str,
    values: tuple[Any, ...],
    candidate_data: Callable[[Any], tuple[CandidateDataDigest, ...]],
) -> AdmittedPortValues:
    """Encode and decode each raw value exactly once at its output Port."""
    admitted = tuple(
        _admitted_from_canonical_bytes(
            port_type=port_type,
            canonical_bytes=port_type.encode(value),
            candidate_data=candidate_data,
        )
        for value in values
    )
    return _admitted_port_snapshot(
        port_type=port_type,
        multiplicity=multiplicity,
        admitted=admitted,
    )


def admitted_port_values_from_bytes(
    *,
    port_type: Any,
    multiplicity: str,
    canonical_values: tuple[bytes, ...],
    candidate_data: Callable[[Any], tuple[CandidateDataDigest, ...]],
) -> AdmittedPortValues:
    """Restore one output Port directly from its canonical stored bytes."""
    admitted = tuple(
        _admitted_from_canonical_bytes(
            port_type=port_type,
            canonical_bytes=value,
            candidate_data=candidate_data,
        )
        for value in canonical_values
    )
    return _admitted_port_snapshot(
        port_type=port_type,
        multiplicity=multiplicity,
        admitted=admitted,
    )


def _admitted_port_snapshot(
    *,
    port_type: Any,
    multiplicity: str,
    admitted: tuple[AdmittedValue, ...],
) -> AdmittedPortValues:
    if multiplicity == "one" and len(admitted) != 1:
        raise PortValueError(
            "Output Port with one multiplicity requires one value"
        )
    content_digest = (
        admitted[0].content_digest
        if len(admitted) == 1
        else canonical_sha256(
            {
                "port_type": port_type.reference(),
                "value_content_digests": [
                    value.content_digest for value in admitted
                ],
            }
        )
    )
    return AdmittedPortValues(
        port_type=port_type.reference(),
        multiplicity=multiplicity,
        values=admitted,
        content_digest=content_digest,
    )


def _output_values(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else (value,)


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


def _normalized_score(
    score: ScoreObservation,
    normalized_ids: Mapping[str, str],
) -> ScoreObservation:
    if type(score) is not ScoreObservation:
        raise PortValueError(
            "Score Collection contains an unsupported entry"
        )
    context = score.context
    if isinstance(context, PairwiseObservationContext):
        context = replace(
            context,
            subject=replace(
                context.subject,
                candidate_id=normalized_ids.get(
                    context.subject.candidate_id,
                    context.subject.candidate_id,
                ),
            ),
            reference=replace(
                context.reference,
                candidate_id=normalized_ids.get(
                    context.reference.candidate_id,
                    context.reference.candidate_id,
                ),
            ),
        )
    return replace(
        score,
        candidate_id=normalized_ids.get(
            score.candidate_id,
            score.candidate_id,
        ),
        context=context,
    )


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
                    "candidate_id": score.candidate_id,
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
                    "context": score.context.to_public(),
                    "source_partition": score.source_partition,
                    "value": score.value,
                }
                for score in entries
            ],
        }
    ).removeprefix("sha256:")


def normalize_scientific_outputs(
    *,
    node_id: str,
    result_identity: str,
    inputs: Mapping[str, Any],
    outputs: Mapping[str, Any],
    candidate_content_digest: Callable[[Candidate], str],
) -> Mapping[str, Any]:
    """Return identity-normalized values without modifying Operation output."""
    input_candidates = {
        candidate.candidate_id: candidate
        for value in inputs.values()
        for candidate in _candidate_values(value)
    }
    normalized_ids: dict[str, str] = {}
    normalized_candidates: dict[str, Candidate] = {}
    normalized_candidate_digests: dict[str, str] = {}
    output_candidates: dict[str, _CandidateOutput] = {}

    for output_port in sorted(outputs):
        for value_index, value in enumerate(
            _output_values(outputs[output_port])
        ):
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

    resolving_candidate_ids: set[str] = set()

    def resolve_candidate(raw_candidate_id: str) -> None:
        if raw_candidate_id in normalized_candidates:
            return
        if raw_candidate_id in resolving_candidate_ids:
            raise PortValueError(
                "Candidate output lineage contains a cycle"
            )

        output = output_candidates[raw_candidate_id]
        candidate = output.candidate
        input_candidate = input_candidates.get(raw_candidate_id)
        if input_candidate is not None:
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
            normalized_candidate_digests[raw_candidate_id] = (
                candidate_content_digest(candidate)
            )
            return

        resolving_candidate_ids.add(raw_candidate_id)
        try:
            parents: list[str] = []
            for parent_id in candidate.parent_ids:
                if parent_id in input_candidates:
                    parents.append(parent_id)
                    continue
                if parent_id not in output_candidates:
                    raise PortValueError(
                        "Candidate parent identity is not a resolved input "
                        "or output Candidate"
                    )
                resolve_candidate(parent_id)
                parents.append(normalized_ids[parent_id])
            parents = list(dict.fromkeys(parents))
            content_digest = candidate_content_digest(candidate)
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
            normalized_id = (
                "candidate-"
                + candidate_identity.removeprefix("sha256:")
            )
            normalized_ids[raw_candidate_id] = normalized_id
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
                    "producer_result_identity": result_identity,
                    "output_port": output.output_port,
                    "sample_slot": sample_slot,
                    "content_digest": content_digest,
                },
            )
            normalized_candidate_digests[raw_candidate_id] = content_digest
        finally:
            resolving_candidate_ids.remove(raw_candidate_id)

    for raw_candidate_id in output_candidates:
        resolve_candidate(raw_candidate_id)

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
                subject = normalized_candidates[
                    entry.subject_candidate_id
                ]
                subject_digest = normalized_candidate_digests[
                    entry.subject_candidate_id
                ]
                reference = normalized_candidates[
                    entry.reference_candidate_id
                ]
                reference_digest = normalized_candidate_digests[
                    entry.reference_candidate_id
                ]
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
                    subject_candidate_id=subject.candidate_id,
                    subject_content_digest=subject_digest,
                    reference_candidate_id=reference.candidate_id,
                    reference_content_digest=reference_digest,
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
                    replace(
                        entry,
                        subject_candidate_id=normalized_ids.get(
                            entry.subject_candidate_id,
                            entry.subject_candidate_id,
                        ),
                        reference_candidate_id=normalized_ids.get(
                            entry.reference_candidate_id,
                            entry.reference_candidate_id,
                        ),
                    )
                    for entry in value.entries
                ]
            )
        if type(value) is CandidatePairingIntent:
            return project_pairing_intent(value)
        if type(value) is ScoreCollection:
            entries = tuple(
                _normalized_score(score, normalized_ids)
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

    normalized_outputs: dict[str, Any] = {}
    for output_port, supplied in outputs.items():
        values = tuple(
            normalize_value(output_port, index, value)
            for index, value in enumerate(_output_values(supplied))
        )
        if isinstance(supplied, list):
            normalized_outputs[output_port] = list(values)
        elif isinstance(supplied, tuple):
            normalized_outputs[output_port] = values
        else:
            normalized_outputs[output_port] = values[0]
    return normalized_outputs
