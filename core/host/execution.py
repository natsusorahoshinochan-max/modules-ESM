"""Execute declared generic nodes and commit their files and terminal records."""
from __future__ import annotations

import json
from collections.abc import Mapping
import shutil

from protein_workbench_public.module_api import Call, Delivery, Outcome, Previous
from .application import HostError
from .storage import receive


class ExecutionRuntime:
    def __init__(self, workdir):
        self.workdir = workdir
        self._cancel = lambda: False
        self.messages = []

    @property
    def cancelled(self):
        return self._cancel()

    def progress(self, message):
        self.messages.append(str(message))


def prepare_group(app, flow, project_id, modules, *, boundary=None):
    from .scopes import SCOPE_TYPES, declaration, validate
    boundary = boundary or {}
    if not isinstance(flow, dict):
        raise HostError("Flow must be an object containing nodes and edges")
    if not isinstance(flow.get("nodes", []), list) or not isinstance(flow.get("edges", []), list):
        raise HostError("Flow nodes and edges must be lists")
    if any(not isinstance(item, dict) for item in flow.get("nodes", []) + flow.get("edges", [])):
        raise HostError("Flow nodes and edges must contain objects")
    available = {node.id: (record, node) for record, module in modules for node in module.nodes}
    tools = {tool.id: (record, tool) for record, module in modules for tool in module.tools}
    nodes = flow.get("nodes", [])
    edges = flow.get("edges", [])
    by_id = {}
    selected = {}
    for instance in nodes:
        identifier = instance.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in by_id:
            raise HostError(f"Invalid or duplicate flow node identity: {identifier!r}")
        by_id[identifier] = instance
        if isinstance(instance.get("type"), str) and instance["type"] in SCOPE_TYPES:
            node = declaration(instance)
            validate(app, instance, node, project_id, modules)
            selected[identifier] = ({"settings": {}}, node)
        elif not isinstance(instance.get("type"), str) or instance["type"] not in available:
            raise HostError(f"Missing module node: {instance.get('type')}")
        else:
            selected[identifier] = available[instance["type"]]
        if not isinstance(instance.get("parameters", {}), dict) or not isinstance(instance.get("inputs", {}), dict) or not isinstance(instance.get("tool_parameters", {}), dict):
            raise HostError(f"Invalid parameters or inputs for node {identifier}")
        _check_tools(instance, selected[identifier][1], tools, identifier)
        _document(app, instance.get('document'), selected[identifier][1], project_id)
    connections = set()
    for edge in edges:
        try:
            source, target = edge["source"], edge["target"]
            output_name, input_name = edge["source_port"], edge["target_port"]
            output = selected[source][1].outputs[output_name]
            accepted = selected[target][1].inputs[input_name]
        except (KeyError, TypeError) as exc:
            raise HostError(f"Connection refers to a missing node or port: {edge}") from exc
        identity = (source, output_name, target, input_name)
        if identity in connections:
            raise HostError(f"Duplicate connection: {identity}")
        connections.add(identity)
        if output.format not in accepted.accepts:
            raise HostError(f"Format {output.format!r} is not accepted by {target}.{input_name}; select an explicit conversion node")
        if output.cardinality == "many" and accepted.cardinality == "one":
            raise HostError(f"Cardinality mismatch: {source}.{output_name} delivers many to {target}.{input_name}")
    for identifier, instance in by_id.items():
        node = selected[identifier][1]
        direct = instance.get("inputs", {})
        if set(direct) - set(node.inputs):
            raise HostError(f"Unknown input port on node {identifier}")
        for name, port in node.inputs.items():
            values = direct.get(name, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise HostError(f"Input {identifier}.{name} must contain an ordered list of package IDs")
            incoming = [edge for edge in edges if edge["target"] == identifier and edge["target_port"] == name]
            supplied = boundary.get((identifier, name), [])
            for source in supplied:
                if not set(source.accepts) <= set(port.accepts):
                    raise HostError(f"Scope input format is not accepted by {identifier}.{name}")
                if source.cardinality == "many" and port.cardinality == "one":
                    raise HostError(f"Scope input cardinality mismatch: {identifier}.{name}")
            count = len(values) + len(incoming) + len(supplied)
            if port.required and not count:
                raise HostError(f"Required input is missing: {identifier}.{name}")
            if port.cardinality == "one" and count > 1:
                raise HostError(f"Cardinality exceeded: {identifier}.{name} accepts one package")
            for package_id in values:
                package = app.package(package_id)
                if package.metadata()["project_id"] != project_id:
                    raise HostError(f"Input package {package_id} is not owned by this project; adopt it before running")
                if package.format not in port.accepts:
                    raise HostError(f"Package format is not accepted by {identifier}.{name}")
    ordered = []
    remaining = dict(by_id)
    while remaining:
        ready = [identifier for identifier in remaining if all(edge["source"] in ordered for edge in edges if edge["target"] == identifier)]
        if not ready:
            raise HostError("Flow contains a connection cycle")
        ordered.extend(ready)
        for identifier in ready:
            remaining.pop(identifier)
    return by_id, selected, edges, ordered


def _document(app, identity, declaration, project_id):
    if identity is None:
        return None
    if not isinstance(identity, str) or not declaration.document_format:
        raise HostError('Node does not accept this editor document')
    package = app.package(identity)
    if package.metadata()['project_id'] != project_id or package.format != declaration.document_format:
        raise HostError('Editor document must belong to the project and match its declared format')
    return package


def prepare(app, flow, project_id, modules):
    # Identity and document shape must be unambiguous before groups can be formed.
    if not isinstance(flow, dict):
        raise HostError("Flow must be an object containing nodes and edges")
    nodes, edges = flow.get("nodes", []), flow.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list) or any(not isinstance(item, dict) for item in nodes + edges):
        raise HostError("Flow nodes and edges must be lists of objects")
    by_id = {}
    for node in nodes:
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in by_id:
            raise HostError(f"Invalid or duplicate flow node identity: {identifier!r}")
        by_id[identifier] = node
    neighbors = {identifier: set() for identifier in by_id}
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        source_known = isinstance(source, str) and source in by_id
        target_known = isinstance(target, str) and target in by_id
        if not source_known and not target_known:
            raise HostError(f"Connection has no existing endpoint: {edge}")
        if source_known and target_known:
            neighbors[source].add(target)
            neighbors[target].add(source)
    visited, groups, selected, ordered = set(), [], {}, []
    for identifier in by_id:
        if identifier in visited:
            continue
        members, pending = set(), [identifier]
        while pending:
            current = pending.pop()
            if current in members:
                continue
            members.add(current)
            pending.extend(neighbors[current] - members)
        visited.update(members)
        group_nodes = [node for node in nodes if node["id"] in members]
        group_edges = [edge for edge in edges if (isinstance(edge.get("source"), str) and edge["source"] in members) or (isinstance(edge.get("target"), str) and edge["target"] in members)]
        group = {"nodes": [node["id"] for node in group_nodes], "diagnostics": []}
        try:
            _, declarations, _, sequence = prepare_group(app, {"nodes": group_nodes, "edges": group_edges}, project_id, modules)
            selected.update(declarations)
            ordered.extend(sequence)
        except HostError as exc:
            group["diagnostics"].append(str(exc))
        groups.append(group)
    return by_id, selected, edges, ordered, groups


def accept(app, run, identifier, declaration, outcome, workdir, progress=()):
    if not isinstance(outcome, Outcome) or outcome.status not in ("succeeded", "failed", "cancelled"):
        raise HostError("Node must return a public Outcome with a valid terminal status")
    if not isinstance(outcome.outputs, Mapping) or set(outcome.outputs) - set(declaration.outputs):
        raise HostError("Node returned undeclared output ports")
    if any(not isinstance(message, str) for message in outcome.diagnostics):
        raise HostError("Outcome diagnostics must be strings")
    try:
        json.dumps(outcome.continuation, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise HostError(f"Continuation must be JSON data: {exc}") from exc
    packages = []
    output_ids = {}
    try:
        for name, port in declaration.outputs.items():
            deliveries = outcome.outputs.get(name, [])
            if not isinstance(deliveries, (list, tuple)):
                raise HostError(f"Output {name} must contain an ordered list of deliveries")
            if port.cardinality == "one" and (len(deliveries) > 1 or outcome.status == "succeeded" and len(deliveries) != 1):
                raise HostError(f"Output {name} requires one delivery on success")
            output_ids[name] = []
            for delivery in deliveries:
                if not isinstance(delivery, Delivery) or delivery.format != port.format:
                    raise HostError(f"Output {name} does not deliver declared format {port.format!r}")
                record = receive(run["project_id"], delivery, workdir, app._packages)
                record["role"] = "output"
                packages.append(record)
                output_ids[name].append(record["id"])
        terminal = {"status": outcome.status, "outputs": output_ids, "diagnostics": list(outcome.diagnostics), "continuation": outcome.continuation, "progress": list(progress)}
        replacement = json.loads(json.dumps(run))
        replacement["nodes"][identifier] = {**replacement["nodes"][identifier], **terminal}
        with app._connect() as connection:
            for package in packages:
                app._write(connection, "package", package)
            app._write(connection, "run", replacement)
        run["nodes"][identifier].update(terminal)
    except BaseException:
        for package in packages:
            shutil.rmtree(app._packages / package["id"], ignore_errors=True)
        raise


def create_run(app, project_id, run_id):
    project = app._get("project", project_id)
    modules = app._modules()
    by_id, selected, edges, ordered, groups = prepare(app, project["flow"], project_id, modules)
    states = {identifier: _initial_state(instance) for identifier, instance in by_id.items()}
    for group in groups:
        if group["diagnostics"]:
            for identifier in group["nodes"]:
                states[identifier].update(status="configuration_blocked", diagnostics=group["diagnostics"])
    run = {"id": run_id, "project_id": project_id, "status": "running", "nodes": states, "groups": groups, "diagnostics": [], "flow": project["flow"], "calls": {}, "scopes": {}}
    tools = {tool.id: (record, tool) for record, module in modules for tool in module.tools}
    app._put("run", run)
    return run, (by_id, selected, edges, ordered, tools)


def _awaits_dependency(run, identifier):
    status = run["nodes"][identifier]["status"]
    return status == "blocked" or status == "cancelled" and identifier not in run["calls"]


def _initial_state(instance, location=None):
    from .scopes import SCOPE_TYPES
    state = {"status": "pending", "outputs": {}, "diagnostics": [], "continuation": None}
    if isinstance(instance.get("type"), str) and instance["type"] in SCOPE_TYPES:
        state["kind"] = "scope"
    if location is not None:
        state.update(kind="scope" if instance.get("type") in SCOPE_TYPES else "node", location=location)
    return state


def _check_tools(instance, node, tools, identifier):
    choices = instance.get("tools", {})
    if any(not isinstance(value, dict) for value in instance.get("tool_parameters", {}).values()):
        raise HostError(f"Tool parameters must be objects on node {identifier}")
    if not isinstance(choices, dict) or set(choices) != set(node.tools):
        raise HostError(f"Select every declared tool slot on node {identifier}")
    for name, slot in node.tools.items():
        choice = choices[name]
        if not isinstance(choice, str) or choice not in tools or tools[choice][1].slot != slot.id:
            raise HostError(f"Selected tool is unavailable or does not implement {slot.id}: {choice}")
    if set(instance.get("tool_parameters", {})) - set(choices):
        raise HostError(f"Unknown tool parameter slot on node {identifier}")


def _instance_for(run, identifier):
    location = run["nodes"][identifier].get("location")
    if location:
        parent = _instance_for(run, location["parent_scope"])
        flow, node_id = parent["scope"]["body"], location["node_id"]
    else:
        flow, node_id = run["flow"], identifier
    return next(node for node in flow["nodes"] if node["id"] == node_id)


def prepare_continuation(app, run, target):
    state = run["nodes"].get(target)
    if run["status"] == "running":
        raise HostError("Run is already executing")
    scope_waiting = state is not None and state["status"] == "cancelled" and target in run.get("scopes", {})
    if state is None or state["status"] not in ("failed", "cancelled") or (target not in run["calls"] and not scope_waiting):
        raise HostError("Selected node has no unfinished continuation")
    root = target
    while run["nodes"][root].get("location"):
        root = run["nodes"][root]["location"]["parent_scope"]
    from .scopes import SCOPE_TYPES, declaration
    modules = app._modules()
    available = {node.id: (record, node) for record, module in modules for node in module.nodes}
    tools = {tool.id: (record, tool) for record, module in modules for tool in module.tools}

    def select(instance, snapshot=None):
        if instance["type"] in SCOPE_TYPES:
            return {"settings": {}}, declaration(instance)
        if instance["type"] not in available:
            raise HostError(f"Missing module node: {instance['type']}")
        record, node = available[instance["type"]]
        _check_tools(instance if snapshot is None else snapshot, node, tools, instance["id"])
        return record, node

    # Successful producers are no longer execution dependencies: fixed inputs
    # refer to already received packages, which remain readable independently.
    select(_instance_for(run, target), run["calls"].get(target))
    by_id = {node["id"]: node for node in run["flow"]["nodes"]}
    edges = run["flow"].get("edges", [])
    candidates = {root}
    while True:
        reachable = {edge["target"] for edge in edges if edge["source"] in candidates and _awaits_dependency(run, edge["target"])}
        if reachable <= candidates:
            break
        candidates.update(reachable)
    selected = {identifier: select(by_id[identifier], run["calls"].get(identifier)) for identifier in candidates}
    ordered = []
    while candidates:
        ready = [identifier for identifier in by_id if identifier in candidates and all(edge["source"] not in candidates for edge in edges if edge["target"] == identifier)]
        if not ready:
            raise HostError("Original continuation flow contains a cycle")
        ordered.extend(ready)
        candidates.difference_update(ready)
    return by_id, selected, edges, ordered, tools


def _execute_leaf(app, run, identifier, instance, record, declaration, inputs, available_tools, cancelled, retry_target):
    previous = json.loads(json.dumps(run["nodes"][identifier]))
    workdir = None
    try:
        if identifier in run["calls"]:
            inputs = run["calls"][identifier]["inputs"]
        else:
            run["calls"][identifier] = {"inputs": inputs, "parameters": instance.get("parameters", {}),
                "tool_parameters": instance.get("tool_parameters", {}), "tools": instance.get("tools", {}),
                **({'document': instance['document']} if instance.get('document') else {})}
        snapshot = run["calls"][identifier]
        run["nodes"][identifier]["status"] = "running"
        app._put("run", run)
        if declaration is None:
            raise HostError(f"Missing module node: {instance['type']}")
        _check_tools(snapshot, declaration, available_tools, identifier)
        if set(inputs) - set(declaration.inputs):
            raise HostError(f"Original call contains an unavailable input port on node {identifier}")
        inputs = {name: list(inputs.get(name, [])) for name in declaration.inputs}
        workdir = app.new_workdir()
        for name, port in declaration.inputs.items():
            count = len(inputs[name])
            if port.required and not count:
                raise HostError(f"Required input is missing: {identifier}.{name}")
            if port.cardinality == "one" and count > 1:
                raise HostError(f"Cardinality exceeded: {identifier}.{name} accepts one package")
            if any(app.package(key).format not in port.accepts for key in inputs[name]):
                raise HostError(f"Package format is not accepted by {identifier}.{name}")
        call = Call(inputs={name: tuple(app.package(package_id) for package_id in values) for name, values in inputs.items()}, parameters=json.loads(json.dumps(snapshot["parameters"])), settings=json.loads(json.dumps(record["settings"])), tool_parameters=json.loads(json.dumps(snapshot["tool_parameters"])), document=_document(app, snapshot.get('document'), declaration, run['project_id']))
        injected = {}
        for name, choice in snapshot["tools"].items():
            owner, tool = available_tools[choice]
            injected[name] = tool.create(json.loads(json.dumps(owner["settings"])))
            if not callable(injected[name]):
                raise HostError(f"Tool factory did not return a callable: {choice}")
        from dataclasses import replace
        call = replace(call, tools=injected, tool_choices=dict(snapshot["tools"]),
            previous=Previous(outputs={name: tuple(app.package(key) for key in keys) for name, keys in previous["outputs"].items()},
                              continuation=previous["continuation"]) if identifier == retry_target and (previous["outputs"] or previous["continuation"] is not None) else None)
        runtime = ExecutionRuntime(workdir)
        runtime._cancel = cancelled
        try:
            outcome = declaration.execute(call, runtime)
        except Exception as exc:
            raise HostError(f"Node execution failed: {exc}") from exc
        if cancelled() and isinstance(outcome, Outcome) and outcome.status == "succeeded":
            outcome = replace(outcome, status="cancelled")
        try:
            accept(app, run, identifier, declaration, outcome, workdir, runtime.messages)
        except Exception as exc:
            raise HostError(f"Output delivery failed: {exc}") from exc
    except Exception as exc:
        run["nodes"][identifier] = {**previous, "status": "cancelled" if cancelled() else "failed", "diagnostics": [str(exc)]}
        app._put("run", run)
    finally:
        if workdir is not None:
            import sys
            pending_error = sys.exception()
            try:
                app._release_workdir(workdir)
            except Exception as cleanup_error:
                detail = f"Work directory cleanup failed: {cleanup_error}"
                if pending_error is not None:
                    raise HostError(f"{pending_error}; {detail}") from cleanup_error
                # Received outputs remain available even if cleanup fails.
                node = run["nodes"][identifier]
                node["status"] = "failed"
                node["diagnostics"].append(detail)
                app._put("run", run)


def _terminal_status(states):
    statuses = {state["status"] for state in states}
    if statuses & {"failed", "blocked", "configuration_blocked"}:
        return "failed"
    if "cancelled" in statuses:
        return "cancelled"
    return "succeeded"


class ScopeScheduler:
    """Revisit persisted children; only the explicitly continued call may retry."""
    def __init__(self, app, run, available_tools, cancelled, retry_target):
        self.app, self.run = app, run
        self.available_tools, self.cancelled, self.retry_target = available_tools, cancelled, retry_target
        self.available = {node.id: (record, node) for record, module in app._modules() for node in module.nodes}
        self.retry_scopes = {retry_target} if retry_target in run["scopes"] else set()
        current = retry_target
        while current and run["nodes"][current].get("location"):
            current = run["nodes"][current]["location"]["parent_scope"]
            self.retry_scopes.add(current)
        if retry_target in run["scopes"]:
            for identifier, state in run["nodes"].items():
                if state.get("kind") != "scope" or state["status"] != "cancelled":
                    continue
                current = identifier
                while run["nodes"][current].get("location"):
                    current = run["nodes"][current]["location"]["parent_scope"]
                    if current == retry_target:
                        self.retry_scopes.add(identifier)
                        break

    def graph(self, by_id, selected, edges, ordered, identifiers, boundary=None):
        from .scopes import SCOPE_TYPES
        boundary = boundary or {}
        for local_id in ordered:
            identifier = identifiers[local_id]
            state = self.run["nodes"][identifier]
            instance = by_id[local_id]
            is_scope = instance["type"] in SCOPE_TYPES
            if state["status"] in ("succeeded", "configuration_blocked"):
                continue
            if identifier in self.run["calls"] and identifier != self.retry_target and state["status"] in ("failed", "cancelled"):
                continue
            if is_scope and state["status"] in ("failed", "cancelled") and identifier in self.run["scopes"] and identifier not in self.retry_scopes:
                continue
            if self.cancelled():
                state.update(status="cancelled", diagnostics=["Run cancelled before this node started"])
                self.app._put("run", self.run)
                continue
            incoming = [edge for edge in edges if edge["target"] == local_id]
            if any(self.run["nodes"][identifiers[edge["source"]]]["status"] != "succeeded" for edge in incoming):
                state.update(status="blocked", diagnostics=["An upstream node did not succeed"])
                self.app._put("run", self.run)
                continue
            record, node = selected.get(local_id, (None, None))
            names = set(instance.get("inputs", {})) | {name for child, name in boundary if child == local_id} | {edge["target_port"] for edge in incoming}
            if node is not None:
                names.update(node.inputs)
            inputs = {name: list(instance.get("inputs", {}).get(name, [])) + list(boundary.get((local_id, name), [])) for name in names}
            for edge in incoming:
                source = self.run["nodes"][identifiers[edge["source"]]]
                inputs[edge["target_port"]].extend(source["outputs"][edge["source_port"]])
            if is_scope:
                self.scope(identifier, instance, node, inputs)
            else:
                _execute_leaf(self.app, self.run, identifier, instance, record, node, inputs, self.available_tools, self.cancelled, self.retry_target)

    def scope(self, identifier, instance, node, inputs):
        from uuid import uuid4
        from .scopes import SCOPE_TYPES, declaration
        run, config = self.run, instance["scope"]
        scope = run["scopes"].setdefault(identifier, {"inputs": json.loads(json.dumps(inputs)), "iterations": []})
        state = run["nodes"][identifier]
        state.update(status="running", diagnostics=[])
        self.app._put("run", run)
        # The boundary snapshot is fixed for this scope invocation. Feedback creates
        # another explicit set of boundary inputs without altering the snapshot.
        fixed = scope["inputs"]
        for name, port in node.inputs.items():
            if (port.required and not fixed[name]) or (port.cardinality == "one" and len(fixed[name]) > 1):
                state.update(status="failed", diagnostics=[f"Scope input cardinality is not satisfied: {name}"])
                self.app._put("run", run)
                return
        is_map = instance["type"] == "host.map"
        count = len(fixed[config["item_input"]]) if is_map else config["rounds"]
        by_id = {child["id"]: child for child in config["body"].get("nodes", [])}
        selected = {key: ({"settings": {}}, declaration(child)) if child["type"] in SCOPE_TYPES else self.available.get(child["type"], (None, None)) for key, child in by_id.items()}
        edges = config["body"].get("edges", [])
        ordered, remaining = [], set(by_id)
        while remaining:
            ready = [key for key in by_id if key in remaining and all(edge["source"] not in remaining for edge in edges if edge["target"] == key)]
            if not ready:
                raise HostError("Scope body contains a connection cycle")
            ordered.extend(ready)
            remaining.difference_update(ready)
        all_succeeded = True
        for index in range(count):
            if self.cancelled():
                state.update(status="cancelled", diagnostics=["Run cancelled before the scope finished"])
                self.app._put("run", run)
                return
            if index == len(scope["iterations"]):
                iteration_inputs = {name: list(keys) for name, keys in fixed.items()}
                if is_map:
                    iteration_inputs[config["item_input"]] = [fixed[config["item_input"]][index]]
                elif index:
                    for name, output in config.get("feedback", {}).items():
                        iteration_inputs[name] = list(scope["iterations"][index - 1]["outputs"][output])
                identifiers = {key: uuid4().hex for key in by_id}
                iteration = {"index": index + 1, "inputs": iteration_inputs, "nodes": identifiers}
                scope["iterations"].append(iteration)
                for key, child_id in identifiers.items():
                    run["nodes"][child_id] = _initial_state(by_id[key], {"parent_scope": identifier, "node_id": key, "item" if is_map else "round": index + 1})
                self.app._put("run", run)
            iteration = scope["iterations"][index]
            identifiers = iteration["nodes"]
            boundary = {}
            for binding in config.get("input_bindings", []):
                boundary.setdefault((binding["node"], binding["port"]), []).extend(iteration["inputs"][binding["input"]])
            self.graph(by_id, selected, edges, ordered, identifiers, boundary)
            children = [run["nodes"][child_id] for child_id in identifiers.values()]
            iteration["status"] = _terminal_status(children)
            if iteration["status"] != "succeeded":
                all_succeeded = False
                if not is_map:
                    break
                continue
            outputs = {name: [] for name in node.outputs}
            for binding in config.get("output_bindings", []):
                outputs[binding["output"]].extend(run["nodes"][identifiers[binding["node"]]]["outputs"][binding["port"]])
            iteration["outputs"] = outputs
            invalid = [name for name, port in node.outputs.items()
                       if port.cardinality == "one" and
                       len(outputs[name]) != 1]
            if invalid:
                iteration["status"] = "failed"
                iteration["diagnostics"] = [f"Scope output cardinality is not satisfied: {name}" for name in invalid]
                all_succeeded = False
                self.app._put("run", run)
                if not is_map:
                    break
                continue
            self.app._put("run", run)
        if all_succeeded:
            outputs = {name: [] for name in node.outputs}
            if is_map:
                for iteration in scope["iterations"]:
                    for name in outputs:
                        outputs[name].extend(iteration["outputs"][name])
            else:
                outputs = scope["iterations"][-1]["outputs"]
            state.update(status="succeeded", outputs=outputs, diagnostics=[])
        else:
            diagnostics = [message for iteration in scope["iterations"] for message in iteration.get("diagnostics", [])]
            state.update(status=_terminal_status({"status": item["status"]} for item in scope["iterations"]), diagnostics=diagnostics or ["A scope child did not succeed; continue its unfinished call"])
        self.app._put("run", run)


def execute(app, run, prepared, cancelled, retry_target=None):
    by_id, selected, edges, ordered, available_tools = prepared
    scheduler = ScopeScheduler(app, run, available_tools, cancelled, retry_target)
    scheduler.graph(by_id, selected, edges, ordered, {key: key for key in by_id})
    run["status"] = _terminal_status(run["nodes"].values())
    return app._put("run", run)
