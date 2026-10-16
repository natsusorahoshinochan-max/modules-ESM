"""Arithmetic means of existing residue observations; never invokes a Provider."""
from dataclasses import asdict
import json
import math

from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from core.operation import OperationCall, OperationContext
from datatypes.i_json import validate_i_json
from datatypes.region import region_residue_ids


class RegionStatisticsImplementation:
    def __init__(self, context: OperationContext) -> None:
        self._method = context.method

    def execute(self, call: OperationCall) -> dict[str, object]:
        source = call.inputs['scores']
        observations = [entry for entry in source.value.entries
                        if entry.metric.contract_id == call.node_parameters['metric_id']]
        if not observations:
            raise ValueError('the selected metric has no observations in this Score Collection')
        entries = []
        policy = call.node_parameters['missing_values']
        for observation in observations:
            axis = observation.residue_axis
            if axis is None or not isinstance(observation.value, (tuple, list)):
                raise ValueError('regional statistics require numeric per-residue observations with their exact axis')
            if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))) for value in observation.value):
                raise ValueError('regional statistics require one numeric value or null per residue, not a matrix')
            region = region_residue_ids(axis.layout, call.node_parameters['region'])
            by_identity = dict(zip(axis.layout.residue_ids, observation.value, strict=True))
            values = [by_identity[identity] for identity in region]
            present = [value for value in values if value is not None]
            if policy == 'require_all' and len(present) != len(values):
                raise ValueError('the selected region contains missing observations; require_all cannot summarize it')
            if not present:
                raise ValueError('the selected region has no observed values')
            entries.append({
                'subject': asdict(observation.subject),
                'source_metric': asdict(observation.metric),
                'source_method': asdict(observation.method),
                'source_context': asdict(observation.context),
                'source_partition': observation.source_partition,
                'source_collection_digest': source.content_digest,
                'residue_axis': asdict(axis),
                'region': list(region), 'selected_count': len(region),
                'valid_count': len(present), 'missing_values': policy,
                'mean': math.fsum(present) / len(present),
                'statistics_method': asdict(self._method),
            })
        return {'statistics': {'entries': entries}}


def validate_statistics(value: object) -> None:
    validate_i_json(value)
    if not isinstance(value, dict) or not isinstance(value.get('entries'), list) or not value['entries']:
        raise ValueError('regional statistics must contain nonempty entries')
    for entry in value['entries']:
        if not isinstance(entry, dict) or not {'subject', 'source_metric', 'source_method', 'source_context',
                'source_partition', 'source_collection_digest', 'residue_axis', 'region', 'selected_count',
                'valid_count', 'missing_values', 'mean', 'statistics_method'} == set(entry):
            raise ValueError('regional statistic must retain its source and region')
        if not (0 < entry['valid_count'] <= entry['selected_count'] == len(entry['region'])):
            raise ValueError('regional statistic counts must describe the selected region')


def wire(value: object) -> object:
    return value


def read_statistics(encoded: bytes) -> dict:
    return json.loads(encoded)['value']


REGION_STATISTICS_PORT_TYPE = PortTypeDefinition(
    'structure_comparison.region_statistics',
    BehaviorReference('structure_comparison.region_statistics.validate'),
    BehaviorReference('structure_comparison.region_statistics.codec'),
    BehaviorReference('structure_comparison.region_statistics.identity'),
    runtime_validator=validate_statistics, runtime_to_wire=wire, runtime_from_wire=wire,
)
