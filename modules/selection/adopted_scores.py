"""Observation capabilities of independently saved Score inputs."""
from collections import Counter
from collections.abc import Iterable
from core.project.adopted_input import AdoptedSnapshot
from core.operation import OperationCall, OperationResources
from core.project.adopted_input import RestoredOutput
from core.catalog.builtins import builtin_port_types
from core.catalog.result_adoption import AdoptedObservation
from datatypes.observation import observation_context_profile, PairwiseContextProfile, PairwiseObservationContext


def adopted_observations(encoded: bytes) -> tuple[AdoptedObservation, ...]:
    port = next(port for port in builtin_port_types() if port.type_id == 'score.collection')
    scores = port.restore(encoded)
    subjects = {score.subject.data_type_id for score in scores}
    pairwise = tuple(score for score in scores if isinstance(score.context, PairwiseObservationContext))
    references = {score.context.reference.candidate.data_type_id for score in pairwise}
    relations = {(score.subject, score.context.reference.candidate) for score in pairwise}
    functional_relation = len(relations) == len({subject for subject, _ in relations})
    groups = {}
    for entry in scores:
        key = (entry.source_partition, entry.metric, entry.method, observation_context_profile(entry.context))
        groups.setdefault(key, Counter())[entry.subject] += 1
    return tuple(AdoptedObservation('value', partition, metric, method, context,
        'one' if all(count == 1 for count in counts.values()) else 'one_or_more',
        subject_output_port='subjects' if len(subjects) == 1 else None,
        reference_output_port='references' if isinstance(context, PairwiseContextProfile) and len(references) == 1 else None,
        pairing_output_port='relation' if isinstance(context, PairwiseContextProfile) and context.pairing_mode == 'explicit_relation' and functional_relation else None)
        for (partition, metric, method, context), counts in groups.items())


def adopted_dependencies(encoded: bytes, values: Iterable[AdoptedSnapshot]) -> tuple[AdoptedSnapshot, ...]:
    """Keep full Candidate values for the exact subjects and comparison references."""
    from dataclasses import replace
    import hashlib
    from datatypes.candidate import CandidateDataReference

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


class AdoptedScoreOperation:
    """Expose the saved observations and their original participant scopes."""
    def __init__(self, resources: OperationResources) -> None:
        self.resources = resources

    def execute(self, call: OperationCall) -> dict[str, RestoredOutput]:
        from core.project.adopted_input import read_adopted_snapshot
        from datatypes.candidate import CandidateCollection, CandidateDataReference
        from datatypes.observation import CandidateRelation, CandidateRelationEntry
        import hashlib

        _, payload = self.resources.read_project_input(call.node_parameters['project_input_ref'])
        snapshot = read_adopted_snapshot(payload)
        ports = {port.type_id: port for port in builtin_port_types()}
        scores = ports['score.collection'].restore(snapshot['canonical_value'].encode())
        outputs = {'value': RestoredOutput(snapshot)}
        candidates = {}
        for dependency in snapshot['dependencies']:
            if dependency['port_type_id'] != 'candidate.collection':
                continue
            collection = ports['candidate.collection'].restore(dependency['canonical_value'].encode())
            by_id = {item.candidate_id: item for item in collection}
            for reference in dependency['candidate_data']:
                candidates[CandidateDataReference(**reference)] = by_id[reference['candidate_id']]

        def output(name, type_id, value, references):
            canonical = ports[type_id].encode(value)
            outputs[name] = RestoredOutput({**snapshot, 'port_type_id': type_id,
                'canonical_value': canonical.decode(), 'content_digest': 'sha256:' + hashlib.sha256(canonical).hexdigest(),
                'candidate_data': [{'candidate_id': ref.candidate_id, 'data_type_id': ref.data_type_id,
                                    'content_digest': ref.content_digest} for ref in references]})

        def scope(name, references):
            references = tuple(dict.fromkeys(references))
            if not references:
                return
            types = {reference.data_type_id for reference in references}
            if len(types) != 1:
                return
            output(name, 'candidate.collection', CandidateCollection(scores.collection_id + '.' + name,
                next(iter(types)), tuple(candidates[ref] for ref in references)), references)

        scope('subjects', (score.subject for score in scores))
        pairwise = tuple(score for score in scores if isinstance(score.context, PairwiseObservationContext))
        scope('references', (score.context.reference.candidate for score in pairwise))
        if pairwise:
            entries = tuple(dict.fromkeys(CandidateRelationEntry(score.subject, score.context.reference.candidate) for score in pairwise))
            if len(entries) == len({entry.subject for entry in entries}):
                output('relation', 'candidate.relation', CandidateRelation(entries),
                       tuple(dict.fromkeys(ref for entry in entries for ref in (entry.subject, entry.reference))))
        return outputs
