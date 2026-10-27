"""The language contract concerns display fields, never scientific values."""
import ast
import importlib
from pathlib import Path

from core.host.registry import validate, node_record
from protein_workbench_public.module_api import Module, Node


def test_official_declarations_expose_bilingual_labels_without_changing_ids():
    tree = ast.parse(Path('protein_workbench_public/bootstrap.py').read_text())
    entries = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'install']
    for entry in entries:
        module = importlib.import_module(entry.split(':')[0]).module()
        validate(module)
        for node in module.nodes:
            assert set(node.name) == {'en', 'zh-CN'}, node.id
            record = node_record(module, node)
            assert record['id'] == node.id
            for key, port in node.inputs.items():
                assert record['inputs'][key]['accepts'] == list(port.accepts)
            for port in (*node.inputs.values(), *node.outputs.values()):
                if port.name is not None:
                    assert isinstance(port.name, dict) and set(port.name) == {'en', 'zh-CN'}, (node.id, port.name)
        for tool in module.tools:
            assert isinstance(tool.name, (dict, str))
            assert isinstance(tool.slot, str)


def test_single_language_external_module_remains_valid():
    module = Module('example', 'External module', nodes=(Node('example.run', 'Run', lambda call, runtime: None),))
    validate(module)
    assert node_record(module, module.nodes[0])['name'] == 'Run'
