"""Observation capabilities of independently saved Score inputs."""
from collections import Counter
from collections.abc import Iterable
from core.project.adopted_input import AdoptedSnapshot
from core.catalog.builtins import builtin_port_types
from core.catalog.result_adoption import AdoptedObservation
from datatypes.observation import observation_context_profile


def adopted_observations(encoded: bytes) -> tuple[AdoptedObservation, ...]:
    port = next(port for port in builtin_port_types() if port.type_id == 'score.collection')
    scores = port.restore(encoded)
    groups = {}
    for entry in scores:
        key = (entry.source_partition, entry.metric, entry.method, observation_context_profile(entry.context))
        groups.setdefault(key, Counter())[entry.subject] += 1
    return tuple(AdoptedObservation('value', partition, metric, method, context,
        'one' if all(count == 1 for count in counts.values()) else 'one_or_more')
        for (partition, metric, method, context), counts in groups.items())


def adopted_dependencies(encoded: bytes, values: Iterable[AdoptedSnapshot]) -> tuple[AdoptedSnapshot, ...]:
    """Keep full Candidate values for the exact subjects and comparison references."""
    from dataclasses import replace
    import hashlib
    from datatypes.candidate import CandidateDataReference
    from datatypes.observation import PairwiseObservationContext

    ports = {port.type_id: port for port in builtin_port_types()}
    scores = ports['score.collection'].restore(encoded)
    required = {entry.subject for entry in scores}
    required_values: set[str] = set()
    for entry in scores:
        if isinstance(entry.context, PairwiseObservationContext):
            required.add(entry.context.reference.candidate)
            required_values.update(digest for digest in (
                entry.context.evidence_content_digest, entry.context.subject_axis_content_digest,
                entry.context.reference_axis_content_digest) if digest is not None)
        if entry.residue_axis is not None:
            required_values.add(entry.residue_axis.axis_content_digest)
            if isinstance(entry.residue_axis.source, CandidateDataReference):
                required.add(entry.residue_axis.source)
    result = []
    for snapshot in values:
        matching_values = required_values.intersection((snapshot['content_digest'], *snapshot['axis_digests']))
        if matching_values:
            result.append(snapshot)
            required_values.difference_update(matching_values)
        if snapshot['port_type_id'] != 'candidate.collection':
            continue
        references = [reference for reference in snapshot['candidate_data']
                      if CandidateDataReference(**reference) in required]
        if not references:
            continue
        identities = {reference['candidate_id'] for reference in references}
        collection = ports['candidate.collection'].restore(snapshot['canonical_value'].encode('utf-8'))
        selected = replace(collection, items=tuple(item for item in collection if item.candidate_id in identities))
        canonical = ports['candidate.collection'].encode(selected)
        result.append({**snapshot, 'canonical_value': canonical.decode('utf-8'),
                       'content_digest': 'sha256:' + hashlib.sha256(canonical).hexdigest(), 'candidate_data': references})
        required.difference_update(CandidateDataReference(**reference) for reference in references)
        if not required and not required_values:
            break
    if required or required_values:
        raise ValueError('Published observations lack required Candidate, residue-axis or alignment values')
    return tuple(result)
