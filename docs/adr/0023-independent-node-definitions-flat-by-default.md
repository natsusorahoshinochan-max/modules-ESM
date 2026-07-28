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
unit. Its unified registration object explicitly binds each Definition to its
implementation or Adapter, and the Registry loads each Definition once.
Contract tests are parameterized over the package's Definitions instead of
requiring repeated per-Node scaffolding. A package-wide YAML that duplicates
Node contracts and mandatory one-directory-per-Node layouts were rejected:
they add parallel sources of truth and recreate the repository's current
boilerplate without serving v2's repository-owned extension scope.

This decision supersedes ADR-0009's fixed `definition.yaml`-per-module layout
while retaining YAML as the only public Node contract. The external precedents
and trade-offs are recorded in
[`2026-07-27-module-package-layout-prior-art.md`](../research/2026-07-27-module-package-layout-prior-art.md).
The registration entry filename and symbol, exact YAML fields, and internal
implementation/test directory names remain separate decisions.
