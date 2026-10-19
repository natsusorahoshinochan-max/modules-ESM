"""Declaration-only module loading; content formats remain module-owned."""
import importlib
import sys
from threading import RLock
from pathlib import Path

from protein_workbench_public.module_api import InputPort, Module, Node, OutputPort, Tool, ToolSlot


import_lock = RLock()


def _locations(module):
    source = getattr(module, "__file__", None)
    return ([source] if source else []) + list(getattr(module, "__path__", ()))


def discard_paths(paths):
    """Evict only objects owned by these application installation directories."""
    paths = {Path(path).resolve() for path in paths}
    def owned(value):
        return any(Path(value).resolve().is_relative_to(path) for path in paths)
    sys.path[:] = [value for value in sys.path if not owned(value)]
    for name, module in list(sys.modules.items()):
        source = getattr(module, "__file__", None)
        locations = list(getattr(module, "__path__", ()))
        if source and owned(source):
            sys.modules.pop(name, None)
        elif any(owned(value) for value in locations):
            remaining = [value for value in locations if not owned(value)]
            if not remaining:
                sys.modules.pop(name, None)
            else:
                module.__path__ = remaining
                if getattr(module, "__spec__", None):
                    module.__spec__.submodule_search_locations = remaining
    importlib.invalidate_caches()


def reconcile(package_root, installed_paths):
    """Converge warm process imports with the caller's locked installation records."""
    root = Path(package_root).resolve()
    active = {Path(path).resolve() for path in installed_paths}
    observed = list(sys.path)
    for module in list(sys.modules.values()):
        observed.extend(_locations(module))
    stale = set()
    for value in observed:
        path = Path(value).resolve()
        if path.is_relative_to(root) and path != root:
            installation = root / path.relative_to(root).parts[0]
            if installation not in active:
                stale.add(installation)
    discard_paths(stale)


def load(entry_point, *, package_path=None):
    from .application import HostError
    with import_lock:
        try:
            module_name, attribute = entry_point.split(":")
            if package_path:
                destination = Path(package_path).resolve()
                for index in range(1, len(module_name.split('.')) + 1):
                    name = '.'.join(module_name.split('.')[:index])
                    cached = sys.modules.get(name)
                    source = getattr(cached, '__file__', None)
                    if source and not Path(source).resolve().is_relative_to(destination):
                        raise ValueError(f"Python import namespace {name!r} already belongs to another package; entry must belong to the selected wheel")
                if str(destination) not in sys.path:
                    sys.path.insert(0, str(destination))
                # Extend shared namespace packages without replacing their valid children.
                for index in range(1, len(module_name.split('.'))):
                    name = '.'.join(module_name.split('.')[:index])
                    cached = sys.modules.get(name)
                    namespace = destination.joinpath(*module_name.split('.')[:index])
                    if cached is not None and not getattr(cached, '__file__', None) and namespace.is_dir():
                        locations = list(cached.__path__)
                        if str(namespace) not in locations:
                            cached.__path__ = locations + [str(namespace)]
                            cached.__spec__.submodule_search_locations = cached.__path__
                importlib.invalidate_caches()
            imported = importlib.import_module(module_name)
            if package_path:
                source = getattr(imported, '__file__', None)
                if not source or not Path(source).resolve().is_relative_to(destination):
                    raise ValueError("Entry point must belong to the selected wheel")
            factory = getattr(imported, attribute)
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
    tool_ids = set()
    for tool in module.tools:
        if not isinstance(tool, Tool) or not all(isinstance(value, str) and value for value in (tool.id, tool.name, tool.slot)) or not callable(tool.create):
            raise ValueError("tool requires id, name, slot and factory")
        if tool.id in tool_ids:
            raise ValueError(f"duplicate tool identity: {tool.id}")
        tool_ids.add(tool.id)
        if not isinstance(tool.parameters, dict) or not isinstance(tool.capabilities, dict):
            raise ValueError("tool parameter and capability declarations must be objects")
        _json_text(tool_record(module, tool))
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
        for name, slot in node.tools.items():
            if not isinstance(name, str) or not name or not isinstance(slot, ToolSlot) or not slot.id or not slot.name:
                raise ValueError("invalid tool slot declaration")
        _json_text(node_record(module, node))


def node_record(module, node):
    return {"id": node.id, "module_id": module.id, "name": node.name, "inputs": {name: {"accepts": list(port.accepts), "cardinality": port.cardinality, "required": port.required} for name, port in node.inputs.items()}, "outputs": {name: {"format": port.format, "cardinality": port.cardinality} for name, port in node.outputs.items()}, "parameters": node.parameters, "tools": {name: {"id": slot.id, "name": slot.name} for name, slot in node.tools.items()}}


def tool_record(module, tool):
    return {"id": tool.id, "module_id": module.id, "name": tool.name, "slot": tool.slot, "parameters": tool.parameters, "capabilities": tool.capabilities}
