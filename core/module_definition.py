"""Module definition: YAML-parsed metadata for a registered module."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PortDefinition:
    """A named, typed port on a module."""

    name: str
    type_id: str
    display_name: str = ""
    description: str = ""
    required: bool = True
    allow_multiple: bool = False


@dataclass(frozen=True)
class InputGroupDefinition:
    """Alternative sets of input Ports that satisfy one Module input mode."""

    name: str
    alternatives: tuple[tuple[str, ...], ...]
    required: bool = True
    allow_multiple: bool = False


@dataclass(frozen=True)
class OutputGroupDefinition:
    """Exactly-one output Port alternatives for one Module result mode."""

    name: str
    alternatives: tuple[tuple[str, ...], ...]


@dataclass
class ParameterDefinition:
    """A configurable module parameter."""

    name: str
    type: str  # int, float, str, bool, enum
    default: object = None
    display_name: str = ""
    description: str = ""
    min_value: float | None = None
    max_value: float | None = None
    options: list[str] | None = None  # for enum type


@dataclass
class ModuleDefinition:
    """Parsed representation of a module's definition.yaml.

    Fields:
        module_id: stable dotted identifier (e.g. 'esm3.generate_sequence').
        version: semver string.
        display_name: human-readable name (may change).
        category: UI grouping (input, prompt, model, conversion, scoring, selection, output).
        description: short prose description.
        input_ports: list of named, typed input ports.
        input_groups: alternative input Port sets with group requirements.
        output_ports: list of named, typed output ports.
        output_groups: alternative output Port sets with group requirements.
        parameters: list of configurable parameters.
        module_api: core-to-module API compatibility version.
    """

    module_id: str
    version: str
    display_name: str
    category: str
    description: str = ""
    input_ports: list[PortDefinition] = field(default_factory=list)
    input_groups: list[InputGroupDefinition] = field(default_factory=list)
    output_ports: list[PortDefinition] = field(default_factory=list)
    output_groups: list[OutputGroupDefinition] = field(default_factory=list)
    parameters: list[ParameterDefinition] = field(default_factory=list)
    module_api: str = "1.0"

    @classmethod
    def from_yaml(cls, path: str | Path) -> ModuleDefinition:
        """Parse a definition.yaml file into a ModuleDefinition."""
        raw = yaml.safe_load(Path(path).read_text())
        return cls._from_dict(raw)

    @classmethod
    def from_yaml_string(cls, content: str) -> ModuleDefinition:
        """Parse a YAML string into a ModuleDefinition (useful for testing)."""
        raw = yaml.safe_load(content)
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict) -> ModuleDefinition:
        """Validate and construct from parsed YAML dict."""
        required = ["module_id", "version", "display_name", "category"]
        for key in required:
            if key not in raw:
                raise ValueError(f"ModuleDefinition missing required field: {key}")

        valid_categories = {
            "input", "prompt", "model", "conversion",
            "scoring", "selection", "output",
        }
        if raw["category"] not in valid_categories:
            raise ValueError(
                f"Invalid category '{raw['category']}'. "
                f"Must be one of: {sorted(valid_categories)}"
            )

        input_ports = []
        for p in raw.get("input_ports", []):
            if "name" not in p or "type_id" not in p:
                raise ValueError("Each input port must have 'name' and 'type_id'")
            input_ports.append(PortDefinition(
                name=p["name"],
                type_id=p["type_id"],
                display_name=p.get("display_name", ""),
                description=p.get("description", ""),
                required=p.get("required", True),
                allow_multiple=p.get("allow_multiple", False),
            ))

        output_ports = []
        for p in raw.get("output_ports", []):
            if "name" not in p or "type_id" not in p:
                raise ValueError("Each output port must have 'name' and 'type_id'")
            output_ports.append(PortDefinition(
                name=p["name"],
                type_id=p["type_id"],
                display_name=p.get("display_name", ""),
                description=p.get("description", ""),
                required=p.get("required", True),
            ))

        output_port_names = {port.name for port in output_ports}
        output_groups = []
        for group in raw.get("output_groups", []):
            alternatives = tuple(
                tuple(alternative)
                for alternative in group.get("alternatives", [])
            )
            if (
                not group.get("name")
                or not alternatives
                or any(not alternative for alternative in alternatives)
            ):
                raise ValueError(
                    "Each output group must have 'name' and 'alternatives'"
                )
            referenced_ports = {
                port_name
                for alternative in alternatives
                for port_name in alternative
            }
            unknown_ports = referenced_ports - output_port_names
            if unknown_ports:
                raise ValueError(
                    f"Output group references unknown Ports: {sorted(unknown_ports)}"
                )
            output_groups.append(OutputGroupDefinition(
                name=group["name"],
                alternatives=alternatives,
            ))

        input_port_names = {port.name for port in input_ports}
        input_groups = []
        for group in raw.get("input_groups", []):
            alternatives = tuple(
                tuple(alternative)
                for alternative in group.get("alternatives", [])
            )
            if (
                not group.get("name")
                or not alternatives
                or any(not alternative for alternative in alternatives)
            ):
                raise ValueError(
                    "Each input group must have 'name' and 'alternatives'"
                )
            referenced_ports = {
                port_name
                for alternative in alternatives
                for port_name in alternative
            }
            unknown_ports = referenced_ports - input_port_names
            if unknown_ports:
                raise ValueError(
                    f"Input group references unknown Ports: {sorted(unknown_ports)}"
                )
            input_groups.append(InputGroupDefinition(
                name=group["name"],
                alternatives=alternatives,
                required=group.get("required", True),
                allow_multiple=group.get("allow_multiple", False),
            ))

        parameters = []
        for p in raw.get("parameters", []):
            if "name" not in p or "type" not in p:
                raise ValueError("Each parameter must have 'name' and 'type'")
            parameters.append(ParameterDefinition(
                name=p["name"],
                type=p["type"],
                default=p.get("default"),
                display_name=p.get("display_name", ""),
                description=p.get("description", ""),
                min_value=p.get("min"),
                max_value=p.get("max"),
                options=p.get("options"),
            ))

        return cls(
            module_id=raw["module_id"],
            version=raw["version"],
            display_name=raw["display_name"],
            category=raw["category"],
            description=raw.get("description", ""),
            input_ports=input_ports,
            input_groups=input_groups,
            output_ports=output_ports,
            output_groups=output_groups,
            parameters=parameters,
            module_api=raw.get("module_api", "1.0"),
        )
