"""Tests for ModuleDefinition YAML parsing."""

import pytest
from core import ModuleDefinition


VALID_YAML = """
module_id: test.module
version: 1.0.0
display_name: Test Module
category: model
description: A test module.
input_ports:
  - name: seq
    type_id: protein.sequence
    display_name: Sequence Input
  - name: struct
    type_id: protein.structure
output_ports:
  - name: result
    type_id: protein.structure
parameters:
  - name: temperature
    type: float
    default: 0.5
    min: 0.0
    max: 2.0
  - name: model_name
    type: enum
    default: default
    options:
      - default
      - fast
module_api: "1.0"
"""


class TestModuleDefinitionParsing:
    def test_valid_yaml_parses_all_fields(self) -> None:
        md = ModuleDefinition.from_yaml_string(VALID_YAML)
        assert md.module_id == "test.module"
        assert md.version == "1.0.0"
        assert md.display_name == "Test Module"
        assert md.category == "model"
        assert md.description == "A test module."
        assert md.module_api == "1.0"

    def test_valid_yaml_parses_input_ports(self) -> None:
        md = ModuleDefinition.from_yaml_string(VALID_YAML)
        assert len(md.input_ports) == 2
        assert md.input_ports[0].name == "seq"
        assert md.input_ports[0].type_id == "protein.sequence"
        assert md.input_ports[0].display_name == "Sequence Input"
        assert md.input_ports[1].name == "struct"
        assert md.input_ports[1].type_id == "protein.structure"

    def test_valid_yaml_parses_output_ports(self) -> None:
        md = ModuleDefinition.from_yaml_string(VALID_YAML)
        assert len(md.output_ports) == 1
        assert md.output_ports[0].name == "result"
        assert md.output_ports[0].type_id == "protein.structure"

    def test_valid_yaml_parses_parameters(self) -> None:
        md = ModuleDefinition.from_yaml_string(VALID_YAML)
        assert len(md.parameters) == 2
        temp = md.parameters[0]
        assert temp.name == "temperature"
        assert temp.type == "float"
        assert temp.default == 0.5
        assert temp.min_value == 0.0
        assert temp.max_value == 2.0

        enum = md.parameters[1]
        assert enum.name == "model_name"
        assert enum.type == "enum"
        assert enum.options == ["default", "fast"]

    def test_minimal_yaml(self) -> None:
        yaml = """
module_id: minimal
version: 0.1.0
display_name: Minimal
category: input
"""
        md = ModuleDefinition.from_yaml_string(yaml)
        assert md.module_id == "minimal"
        assert md.input_ports == []
        assert md.output_ports == []
        assert md.parameters == []

    def test_missing_module_id_raises(self) -> None:
        with pytest.raises(ValueError, match="missing required field"):
            ModuleDefinition.from_yaml_string(
                "version: 1.0\ndisplay_name: X\ncategory: input"
            )

    def test_missing_version_raises(self) -> None:
        with pytest.raises(ValueError, match="missing required field"):
            ModuleDefinition.from_yaml_string(
                "module_id: x\ndisplay_name: X\ncategory: input"
            )

    def test_invalid_category_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid category"):
            ModuleDefinition.from_yaml_string(
                "module_id: x\nversion: 1.0\ndisplay_name: X\ncategory: invalid_cat"
            )

    def test_port_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="must have 'name' and 'type_id'"):
            ModuleDefinition.from_yaml_string(
                "module_id: x\nversion: 1.0\ndisplay_name: X\ncategory: input\n"
                "input_ports:\n  - type_id: text"
            )

    def test_port_missing_type_id_raises(self) -> None:
        with pytest.raises(ValueError, match="must have 'name' and 'type_id'"):
            ModuleDefinition.from_yaml_string(
                "module_id: x\nversion: 1.0\ndisplay_name: X\ncategory: input\n"
                "input_ports:\n  - name: text"
            )

    def test_parameter_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="must have 'name' and 'type'"):
            ModuleDefinition.from_yaml_string(
                "module_id: x\nversion: 1.0\ndisplay_name: X\ncategory: input\n"
                "parameters:\n  - type: int"
            )

    def test_defaults_are_applied(self) -> None:
        yaml = """
module_id: defaults.test
version: 1.0.0
display_name: Defaults
category: input
"""
        md = ModuleDefinition.from_yaml_string(yaml)
        assert md.description == ""
        assert md.module_api == "1.0"
        assert md.input_ports == []
        assert md.output_ports == []
        assert md.parameters == []
