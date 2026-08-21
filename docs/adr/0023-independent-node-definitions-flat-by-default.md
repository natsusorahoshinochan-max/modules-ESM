---
status: accepted
---

# Node Definitions are independent and flat by default

Each Node Type owns exactly one independent YAML Node Definition. Within a
Module Package, Definitions are stored flat under `definitions/` by default;
a Node-specific resource or test subdirectory exists only when that Node has
genuinely dedicated templates, scripts, large fixtures, or golden files.
Definitions, Python implementations, Adapters, tests, and directories do not
have a one-to-one mapping, so cohesive implementations and test fixtures may be
shared by several Node Types.

The Module Package remains the sole startup discovery and atomic registration
unit. Its unified registration object explicitly lists every Node and Metric
Definition resource, binds each Node Definition to its Execution Bindings, and
loads each resource once. Resource globs, recursive scanning, and helper-driven
automatic enumeration are forbidden. Unknown schema fields fail startup.
Contract tests are parameterized over the package's Definitions instead of
requiring repeated per-Node scaffolding. One independent Definition per Node
Type and one explicit registration list prevent parallel sources of truth.

YAML is the only public Node contract format.
ADR-0018 fixes the production registration entry as
`modules/<package_name>/package.py:MODULE_PACKAGE`. Node Definition YAML owns
only Node identity, display metadata, Ports and groups, and cross-Binding
parameters. Metric Definition YAML owns Metric identity, value shape and type,
unit, direction, canonical range, granularity, aggregation, validity or masking,
and Observation Context schema. Method, Binding, Port Type, Utility Transform,
and factory or probe contracts use immutable typed Python registration.

A simple package may use `implementation.py` or `adapters.py` and move to
`implementations/` or `adapters/` only when several cohesive implementations
exist. Optional resources and package-local source tests are created only when
needed; tests are excluded from the production wheel. Directory choice does not
change the production registration contract. ADR-0028 defines the referenced
Port Type contracts.
