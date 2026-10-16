"""Selection-owned observation discovery for an unfinished authoring graph."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib.resources import files
from typing import Any, TYPE_CHECKING

import yaml

from core.catalog.authoring_actions import AuthoringActionContext, AuthoringActionDefinition
from core.catalog.observation import ObservationPropagationFilter
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import canonical_json_bytes
from datatypes.observation import ObservationContextProfile, observation_context_profile_descriptor
from core.workflow.document import WORKFLOW_SCHEMA_VERSION
from protein_workbench_public.protocol import validate_schema
from protein_workbench_public.workflow_codec import decode_workflow_document

if TYPE_CHECKING:
    from core.workflow.authoring import WorkflowAuthoringDescription

_SCHEMA = yaml.safe_load(files(__package__).joinpath('definitions/authoring-schema.yaml').read_text())
type _Source = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _ObservationCapability:
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference | None
    context_profile: ObservationContextProfile
    guaranteed_multiplicity: str
    subject_source: _Source | None
    reference_source: _Source | None
    pairing_source: _Source | None


def _connected_source(description: WorkflowAuthoringDescription, node_id: str, port: str) -> _Source | None:
    sources = description.graph.input_sources.get(node_id, {}).get(port, ())
    if len(sources) != 1:
        return None
    source = sources[0][1]
    return source.node_id, source.output_port


def _capability_source(description: WorkflowAuthoringDescription, node_id: str,
                       direction: str | None, port: str | None) -> _Source | None:
    if port is None:
        return None
    return (node_id, port) if direction == 'output' else _connected_source(description, node_id, port)


def _matches_filter(capability: _ObservationCapability, filter: ObservationPropagationFilter) -> bool:
    return ((filter.source_partition is None or capability.source_partition == filter.source_partition)
        and (filter.metric is None or capability.metric == filter.metric)
        and (filter.method is None or capability.method == filter.method)
        and (filter.context_profile is None or capability.context_profile == filter.context_profile))


def _derive_observations(description: WorkflowAuthoringDescription) -> dict[_Source, tuple[_ObservationCapability, ...]]:
    capabilities: dict[_Source, tuple[_ObservationCapability, ...]] = {}
    graph, catalog = description.graph, description.catalog
    for node_id in graph.node_order:
        if node_id not in graph.output_ports_by_node:
            continue
        for observation in description.adopted_observations.get(node_id, ()):
            key = node_id, observation.output_port
            capabilities[key] = (*capabilities.get(key, ()), _ObservationCapability(
                observation.source_partition, observation.metric, observation.method, observation.context_profile,
                observation.guaranteed_multiplicity,
                (node_id, observation.subject_output_port) if observation.subject_output_port else None,
                (node_id, observation.reference_output_port) if observation.reference_output_port else None,
                (node_id, observation.pairing_output_port) if observation.pairing_output_port else None))
        plan = catalog.produced_observation_plan(graph.nodes_by_id[node_id].binding_id)
        for declaration in plan.observations:
            method = plan.binding_method
            if declaration.method_source is not None and declaration.method_source.direction == 'input':
                source = _connected_source(description, node_id, declaration.method_source.port)
                method = (catalog.produced_observation_plan(graph.nodes_by_id[source[0]].binding_id).binding_method
                    if source is not None else None)
            capability = _ObservationCapability(
                declaration.output_partition, declaration.metric, method, declaration.context_profile,
                declaration.guaranteed_multiplicity,
                _capability_source(description, node_id, 'input', declaration.subject_input),
                _capability_source(description, node_id,
                    declaration.reference_source.direction if declaration.reference_source else None,
                    declaration.reference_source.port if declaration.reference_source else None),
                _capability_source(description, node_id,
                    declaration.pairing_source.direction if declaration.pairing_source else None,
                    declaration.pairing_source.port if declaration.pairing_source else None))
            key = node_id, declaration.output_port
            capabilities[key] = (*capabilities.get(key, ()), capability)
        propagation = plan.propagation
        if propagation is None:
            continue
        propagated = []
        for port in propagation.input_ports:
            for _, source in graph.input_sources.get(node_id, {}).get(port, ()):
                propagated.extend(capabilities.get((source.node_id, source.output_port), ()))
        if propagation.mode == 'filter':
            propagated = [item for item in propagated if _matches_filter(item, propagation.filter)]
        capabilities[(node_id, propagation.output_port)] = tuple({
            canonical_json_bytes(asdict(item)): item for item in propagated}.values())
    return capabilities


def observation_options(context: AuthoringActionContext, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """List declared scalar measurements without executing or completing the graph.

    Pairwise measurements remain eligible before the user chooses their exact
    reference or Context. Runtime Selection requires an unambiguous exact match.
    """
    validate_schema('#/$defs/SelectionObservationOptionsRequest', parameters, definitions=_SCHEMA)
    workflow = decode_workflow_document({'schema_version': WORKFLOW_SCHEMA_VERSION,
        'workflow_id': context.project_id, **parameters['workflow']})
    description = context.workflow_authoring.describe(context.project_id, workflow, input_reader=context.read_input)
    options = []
    for (node_id, port), capabilities in _derive_observations(description).items():
        for capability in capabilities:
            metric = description.catalog.require_contract('metric', capability.metric.contract_id)
            if metric.descriptor['value_shape'] != 'scalar' or capability.method is None:
                continue
            options.append({'source': {'node_id': node_id, 'output_port': port},
                'partition': capability.source_partition, 'metric_id': capability.metric.contract_id,
                'method_id': capability.method.contract_id,
                'context': observation_context_profile_descriptor(capability.context_profile)})
    return {'options': options}


AUTHORING_ACTIONS = (AuthoringActionDefinition('selection.observation_options', observation_options),)
