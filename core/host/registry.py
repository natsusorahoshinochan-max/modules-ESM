"""Declaration-only module loading; content formats remain module-owned."""
import importlib
from pathlib import Path

from protein_workbench_public.module_api import InputPort, Module, Node, OutputPort


def load(entry_point):
    from .application import HostError
    try:
        module_name, attribute = entry_point.split(":")
        factory = getattr(importlib.import_module(module_name), attribute)
        if not callable(factory):
            raise ValueError("entry must be callable")
        declaration = factory()
        validate(declaration)
        return declaration
    except Exception as exc:
        raise HostError(f"Could not load module entry {entry_point!r}: {exc}") from exc


def validate(module):
    from .application import _json_text
    if not isinstance(module, Module):
        raise ValueError("entry must return public Module declaration")
    if not module.id or not isinstance(module.id, str) or not isinstance(module.name, str) or not module.name:
        raise ValueError("module id and name are required")
    _json_text(module.settings)
    if not isinstance(module.settings, dict):
        raise ValueError("settings declaration must be an object")
    if module.ui is not None and (not isinstance(module.ui, str) or not Path(module.ui).is_absolute() or not Path(module.ui).is_file()):
        raise ValueError("UI entry must name an existing absolute file")
    seen = set()
    for node in module.nodes:
        if not isinstance(node, Node) or not isinstance(node.id, str) or not node.id or not isinstance(node.name, str) or not node.name or not callable(node.execute):
            raise ValueError("node requires id, name and executable entry")
        if node.id in seen:
            raise ValueError(f"duplicate node identity: {node.id}")
        seen.add(node.id)
        if not isinstance(node.parameters, dict):
            raise ValueError("node parameter declaration must be an object")
        for name, port in node.inputs.items():
            if not isinstance(name, str) or not name or not isinstance(port, InputPort):
                raise ValueError("invalid input port declaration")
            if not isinstance(port.accepts, (tuple, list)) or not port.accepts or any(not isinstance(item, str) or not item for item in port.accepts) or port.cardinality not in ("one", "many") or not isinstance(port.required, bool):
                raise ValueError(f"invalid input declaration: {name}")
        for name, port in node.outputs.items():
            if not isinstance(name, str) or not name or not isinstance(port, OutputPort) or not isinstance(port.format, str) or not port.format or port.cardinality not in ("one", "many"):
                raise ValueError(f"invalid output declaration: {name}")
        _json_text(node_record(module, node))


def node_record(module, node):
    return {"id": node.id, "module_id": module.id, "name": node.name, "inputs": {name: {"accepts": list(port.accepts), "cardinality": port.cardinality, "required": port.required} for name, port in node.inputs.items()}, "outputs": {name: {"format": port.format, "cardinality": port.cardinality} for name, port in node.outputs.items()}, "parameters": node.parameters}
