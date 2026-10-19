"""Execute declared generic nodes and commit their files and terminal records."""
from __future__ import annotations

import json
from collections.abc import Mapping
import shutil

from protein_workbench_public.module_api import Call, Delivery, Outcome
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


def prepare_group(app, flow, project_id, modules):
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
        if not isinstance(instance.get("type"), str) or instance["type"] not in available:
            raise HostError(f"Missing module node: {instance.get('type')}")
        selected[identifier] = available[instance["type"]]
        if not isinstance(instance.get("parameters", {}), dict) or not isinstance(instance.get("inputs", {}), dict) or not isinstance(instance.get("tool_parameters", {}), dict):
            raise HostError(f"Invalid parameters or inputs for node {identifier}")
        choices = instance.get("tools", {})
        if any(not isinstance(value, dict) for value in instance.get("tool_parameters", {}).values()):
            raise HostError(f"Tool parameters must be objects on node {identifier}")
        if not isinstance(choices, dict) or set(choices) != set(selected[identifier][1].tools):
            raise HostError(f"Select every declared tool slot on node {identifier}")
        for name, slot in selected[identifier][1].tools.items():
            choice = choices[name]
            if not isinstance(choice, str) or choice not in tools or tools[choice][1].slot != slot.id:
                raise HostError(f"Selected tool is unavailable or does not implement {slot.id}: {choice}")
        if set(instance.get("tool_parameters", {})) - set(choices):
            raise HostError(f"Unknown tool parameter slot on node {identifier}")
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
            count = len(values) + len(incoming)
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


def accept(app, run, identifier, declaration, outcome, workdir):
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
                packages.append(record)
                output_ids[name].append(record["id"])
        terminal = {"status": outcome.status, "outputs": output_ids, "diagnostics": list(outcome.diagnostics), "continuation": outcome.continuation}
        replacement = json.loads(json.dumps(run))
        replacement["nodes"][identifier] = terminal
        with app._connect() as connection:
            for package in packages:
                app._write(connection, "package", package)
            app._write(connection, "run", replacement)
        run.update(replacement)
    except BaseException:
        for package in packages:
            shutil.rmtree(app._packages / package["id"], ignore_errors=True)
        raise


def create_run(app, project_id, run_id):
    project = app._get("project", project_id)
    modules = app._modules()
    by_id, selected, edges, ordered, groups = prepare(app, project["flow"], project_id, modules)
    states = {identifier: {"status": "pending", "outputs": {}, "diagnostics": [], "continuation": None} for identifier in by_id}
    for group in groups:
        if group["diagnostics"]:
            for identifier in group["nodes"]:
                states[identifier].update(status="configuration_blocked", diagnostics=group["diagnostics"])
    run = {"id": run_id, "project_id": project_id, "status": "running", "nodes": states, "groups": groups, "diagnostics": [], "flow": project["flow"]}
    tools = {tool.id: (record, tool) for record, module in modules for tool in module.tools}
    app._put("run", run)
    return run, (by_id, selected, edges, ordered, tools)


def execute(app, run, prepared, cancelled):
    by_id, selected, edges, ordered, available_tools = prepared
    for identifier in ordered:
        if cancelled():
            run["nodes"][identifier]["status"] = "cancelled"
            run["nodes"][identifier]["diagnostics"] = ["Run cancelled before this node started"]
            app._put("run", run)
            continue
        incoming = [edge for edge in edges if edge["target"] == identifier]
        if any(run["nodes"][edge["source"]]["status"] != "succeeded" for edge in incoming):
            run["nodes"][identifier]["status"] = "blocked"
            run["nodes"][identifier]["diagnostics"] = ["An upstream node did not succeed"]
            app._put("run", run)
            continue
        workdir = None
        try:
            run["nodes"][identifier]["status"] = "running"
            app._put("run", run)
            instance = by_id[identifier]
            record, declaration = selected[identifier]
            inputs = {name: list(instance.get("inputs", {}).get(name, [])) for name in declaration.inputs}
            for edge in incoming:
                inputs[edge["target_port"]].extend(run["nodes"][edge["source"]]["outputs"][edge["source_port"]])
            workdir = app.new_workdir()
            for name, port in declaration.inputs.items():
                count = len(inputs[name])
                if port.required and not count:
                    raise HostError(f"Required input is missing: {identifier}.{name}")
                if port.cardinality == "one" and count > 1:
                    raise HostError(f"Cardinality exceeded: {identifier}.{name} accepts one package")
            call = Call(inputs={name: tuple(app.package(package_id) for package_id in values) for name, values in inputs.items()}, parameters=json.loads(json.dumps(instance.get("parameters", {}))), settings=json.loads(json.dumps(record["settings"])), tool_parameters=json.loads(json.dumps(instance.get("tool_parameters", {}))))
            injected = {}
            for name, choice in instance.get("tools", {}).items():
                owner, tool = available_tools[choice]
                injected[name] = tool.create(json.loads(json.dumps(owner["settings"])))
                if not callable(injected[name]):
                    raise HostError(f"Tool factory did not return a callable: {choice}")
            from dataclasses import replace
            call = replace(call, tools=injected, tool_choices=dict(instance.get("tools", {})))
            runtime = ExecutionRuntime(workdir)
            runtime._cancel = cancelled
            try:
                outcome = declaration.execute(call, runtime)
            except Exception as exc:
                raise HostError(f"Node execution failed: {exc}") from exc
            if cancelled() and isinstance(outcome, Outcome) and outcome.status == "succeeded":
                outcome = replace(outcome, status="cancelled")
            try:
                accept(app, run, identifier, declaration, outcome, workdir)
            except Exception as exc:
                raise HostError(f"Output delivery failed: {exc}") from exc
        except Exception as exc:
            run["nodes"][identifier] = {"status": "cancelled" if cancelled() else "failed", "outputs": {}, "diagnostics": [str(exc)], "continuation": None}
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
    statuses = {node["status"] for node in run["nodes"].values()}
    run["status"] = "failed" if "failed" in statuses or "blocked" in statuses or "configuration_blocked" in statuses else "cancelled" if "cancelled" in statuses else "succeeded"
    return app._put("run", run)
