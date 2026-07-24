"""Tests for ModuleRegistry and discover_modules()."""

import pytest
from core import ModuleDefinition, ModuleRegistry, TypeRegistry, discover_modules


STUB_YAML = """
module_id: stub.echo
version: 1.0.0
display_name: Echo
category: input
input_ports:
  - name: text
    type_id: text
output_ports:
  - name: text
    type_id: text
parameters:
  - name: repeat
    type: int
    default: 1
module_api: "1.0"
"""


class TestModuleRegistry:
    def test_register_and_get(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        md = ModuleDefinition.from_yaml_string(STUB_YAML)
        mr.register(md)
        assert mr.get("stub.echo") is not None
        assert mr.get("stub.echo").display_name == "Echo"

    def test_register_duplicate_raises(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        md = ModuleDefinition.from_yaml_string(STUB_YAML)
        mr.register(md)
        with pytest.raises(ValueError, match="already registered"):
            mr.register(md)

    def test_register_auto_registers_port_types(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        md = ModuleDefinition.from_yaml_string(STUB_YAML)
        mr.register(md)
        assert "text" in tr.list_all()

    def test_contains(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        md = ModuleDefinition.from_yaml_string(STUB_YAML)
        mr.register(md)
        assert "stub.echo" in mr
        assert "nonexistent" not in mr

    def test_list_all(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        md1 = ModuleDefinition.from_yaml_string(STUB_YAML)
        mr.register(md1)
        md2 = ModuleDefinition.from_yaml_string(
            STUB_YAML.replace("stub.echo", "stub.echo2").replace("Echo", "Echo2")
        )
        mr.register(md2)
        modules = mr.list_all()
        assert len(modules) == 2
        ids = {m.module_id for m in modules}
        assert ids == {"stub.echo", "stub.echo2"}

    def test_list_by_category(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        md_input = ModuleDefinition.from_yaml_string(STUB_YAML)
        mr.register(md_input)
        md_model = ModuleDefinition.from_yaml_string(
            STUB_YAML.replace("stub.echo", "stub.model")
            .replace("Echo", "Model")
            .replace("category: input", "category: model")
        )
        mr.register(md_model)
        grouped = mr.list_by_category()
        assert "input" in grouped
        assert "model" in grouped
        assert len(grouped["input"]) == 1
        assert len(grouped["model"]) == 1

    def test_len(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        assert len(mr) == 0
        mr.register(ModuleDefinition.from_yaml_string(STUB_YAML))
        assert len(mr) == 1

    def test_get_nonexistent(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        assert mr.get("nonexistent") is None


class TestDiscoverModules:
    def test_discovers_stub_module(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        assert "stub.echo" in mr
        mod = mr.get("stub.echo")
        assert mod is not None
        assert mod.module_id == "stub.echo"
        assert mod.version == "1.0.0"
        assert mod.category == "input"
        assert len(mod.input_ports) == 1
        assert len(mod.output_ports) == 1
        assert len(mod.parameters) == 2
        assert "text" in tr.list_all()

    def test_discover_is_idempotent(self) -> None:
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        # Second discovery should not raise — idempotent
        discover_modules(mr)
        assert "stub.echo" in mr
