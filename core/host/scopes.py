"""Explicit package boundaries for generic Map and Repeat graphs."""
from collections import defaultdict
from dataclasses import replace

from protein_workbench_public.module_api import InputPort, Node, OutputPort

from .application import HostError

SCOPE_TYPES = frozenset(('host.map', 'host.repeat'))


def walk_nodes(flow, *, strict=False):
    """Visit direct input owners at every scope depth, including incomplete drafts."""
    nodes = flow.get('nodes', []) if isinstance(flow, dict) else None
    if not isinstance(nodes, list):
        if strict:
            raise HostError('Flow nodes must be a list')
        return
    for node in nodes:
        if not isinstance(node, dict):
            if strict:
                raise HostError('Flow nodes must contain objects')
            continue
        yield node
        if isinstance(node.get('type'), str) and node['type'] in SCOPE_TYPES:
            scope = node.get('scope', {})
            body = scope.get('body', {}) if isinstance(scope, dict) else None
            yield from walk_nodes(body, strict=strict)


def _scope_only(_call, _runtime):
    raise HostError('Scopes are executed by the graph scheduler')


def declaration(instance):
    config = instance.get('scope')
    if not isinstance(config, dict):
        raise HostError(f"Scope configuration is missing: {instance['id']}")
    inputs, outputs = config.get('inputs', {}), config.get('outputs', {})
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        raise HostError('Scope ports must be named objects')
    declared_inputs, declared_outputs = {}, {}
    for name, port in inputs.items():
        if not isinstance(name, str) or not name or not isinstance(port, dict):
            raise HostError('Invalid scope input port')
        accepts = port.get('accepts')
        if not isinstance(accepts, list) or not accepts or any(not isinstance(fmt, str) or not fmt for fmt in accepts):
            raise HostError(f'Scope input formats must be a nonempty string list: {name}')
        if port.get('cardinality', 'one') not in ('one', 'many') or not isinstance(port.get('required', True), bool):
            raise HostError(f'Invalid scope input cardinality or required flag: {name}')
        declared_inputs[name] = InputPort(tuple(accepts), port.get('cardinality', 'one'), port.get('required', True))
    for name, port in outputs.items():
        if not isinstance(name, str) or not name or not isinstance(port, dict) or not isinstance(port.get('format'), str) or not port['format']:
            raise HostError('Scope outputs require named formats')
        if port.get('cardinality', 'one') not in ('one', 'many'):
            raise HostError(f'Invalid scope output cardinality: {name}')
        if instance['type'] == 'host.map' and port.get('cardinality', 'one') != 'many':
            raise HostError('Map outputs must accept many packages')
        declared_outputs[name] = OutputPort(port['format'], port.get('cardinality', 'one'))
    if instance['type'] == 'host.map':
        if config.get('item_input') not in declared_inputs:
            raise HostError('Map must select an existing item_input port')
    elif type(config.get('rounds')) is not int or config['rounds'] < 1:
        raise HostError('Repeat rounds must be a positive integer')
    if instance.get('parameters') or instance.get('tools') or instance.get('tool_parameters'):
        raise HostError('Scope execution is configured in scope; tools belong to its child nodes')
    return Node(instance['type'], instance['type'], _scope_only, inputs=declared_inputs, outputs=declared_outputs)


def validate(app, instance, node, project_id, modules):
    from .execution import prepare_group
    config = instance['scope']
    boundary = defaultdict(list)
    for name in ('input_bindings', 'output_bindings'):
        if not isinstance(config.get(name, []), list) or any(not isinstance(item, dict) for item in config.get(name, [])):
            raise HostError(f'Scope {name} must be a list of connections')
    seen = set()
    for binding in config.get('input_bindings', []):
        source, target, port = binding.get('input'), binding.get('node'), binding.get('port')
        if any(not isinstance(value, str) or not value for value in (source, target, port)) or source not in node.inputs:
            raise HostError(f'Scope input connection refers to a missing port: {binding}')
        identity = (source, target, port)
        if identity in seen:
            raise HostError(f'Duplicate scope input connection: {binding}')
        seen.add(identity)
        supplied = node.inputs[source]
        if instance['type'] == 'host.map' and source == config['item_input']:
            supplied = replace(supplied, cardinality='one', required=True)
        boundary[(target, port)].append(supplied)
    body, selected, _, _ = prepare_group(app, config.get('body'), project_id, modules, boundary=boundary)
    for target, port in boundary:
        if target not in body or port not in selected[target][1].inputs:
            raise HostError(f'Scope input connection refers to a missing node or port: {target}.{port}')
    seen, counts = set(), defaultdict(int)
    for binding in config.get('output_bindings', []):
        source, port, target = binding.get('node'), binding.get('port'), binding.get('output')
        if any(not isinstance(value, str) or not value for value in (source, port, target)):
            raise HostError(f'Invalid scope output connection: {binding}')
        identity = (source, port, target)
        if identity in seen:
            raise HostError(f'Duplicate scope output connection: {binding}')
        seen.add(identity)
        try:
            output = selected[source][1].outputs[port]
            outer = node.outputs[target]
        except KeyError as exc:
            raise HostError(f'Scope output connection refers to a missing node or port: {binding}') from exc
        if output.format != outer.format:
            raise HostError(f'Scope output format mismatch: {source}.{port} -> {target}')
        counts[target] += 1
        if outer.cardinality == 'one' and (output.cardinality == 'many' or counts[target] > 1):
            raise HostError(f'Scope output cardinality exceeded: {target}')
    if set(node.outputs) != set(counts):
        raise HostError('Every scope output must have an explicit connection')
    if instance['type'] == 'host.repeat':
        feedback = config.get('feedback', {})
        if not isinstance(feedback, dict):
            raise HostError('Repeat feedback must map input names to output names')
        for target, source in feedback.items():
            if not isinstance(source, str) or target not in node.inputs or source not in node.outputs:
                raise HostError(f'Repeat feedback refers to a missing port: {target} <- {source}')
            output, accepted = node.outputs[source], node.inputs[target]
            if output.format not in accepted.accepts:
                raise HostError(f'Repeat feedback format mismatch: {target} <- {source}')
            if output.cardinality == 'many' and accepted.cardinality == 'one':
                raise HostError(f'Repeat feedback cardinality mismatch: {target} <- {source}')
