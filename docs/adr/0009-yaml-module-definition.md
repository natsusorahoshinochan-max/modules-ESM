---
status: superseded by ADR-0023
---

# ModuleDefinition uses YAML files

ADR-0023 retains YAML as the public Node Definition format while replacing the
v1 `definition.yaml`-per-module layout. The text below is retained as the
historical v1 decision.

Each module declares its identity, ports, and parameters in a definition.yaml
file, following the format in the architecture document section 7.2. The module
registry loads and validates these definitions at startup.

Python-inline definitions were considered and rejected. YAML matches the
architecture document's stated format exactly, is readable by non-developers,
and avoids coupling the definition syntax to Python's import system.

The YAML is parsed into a ModuleDefinition dataclass at load time. All
downstream consumers (execution engine, type checker, parameter validator)
work with the Python object, not raw YAML.
