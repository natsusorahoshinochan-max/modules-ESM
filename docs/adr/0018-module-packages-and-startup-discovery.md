---
status: accepted
---

# Module Packages are the startup extension boundary

Repository maintainers extend Protein Workbench by adding or extending a
cohesive Module Package, which may provide multiple scientific Node Types. Each
package contributes one unified registration object containing its YAML public
Definitions, Execution Bindings, Metric Definitions, availability checks, and
contract-test cases; adding a conforming package must not require a change to
`core/`.

Each immediate child directory under `modules/` is one discovery unit and
exports exactly one explicit `ModulePackage` registration object. Discovery
scans only those package roots and consumes that object; it does not recursively
search for arbitrary `definition.yaml` files, invoke per-Node `register()`
functions, or depend on import side effects. A future decision may choose the
entry-point filename and internal package layout without changing this
boundary.

Discovery occurs only at startup and the resulting registries are immutable. A
package entry point must not eagerly import optional provider dependencies:
their absence is reported by availability checks. Malformed Definitions,
package import or registration failures, and conflicting contracts fail startup
atomically. ADR-0025 refines availability to the Execution Binding: a valid
Node Type remains discovered while each binding whose optional model, runtime,
accelerator, binary, or credentials are absent has its own structured
`unavailable` state.

The v2 boundary intentionally supports repository-owned developer extensions,
not third-party `pip install`, plugin management, runtime hot loading, or
automatic dependency installation. The Registry consumes a single Module
Package registration shape so a future Python entry-point discovery mechanism
can supply the same object without changing the package contract.

This decision supersedes ADR-0007.
