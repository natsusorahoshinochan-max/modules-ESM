---
status: accepted
---

# Module Packages are the startup extension boundary

Repository maintainers extend Protein Workbench by adding or extending a
cohesive Module Package, which may provide multiple scientific Node Types. Each
package contributes one immutable typed production registration object. It
explicitly lists every YAML Node Definition and Metric Definition resource and
registers its Methods, Execution Bindings, optional Port Type Definitions,
Utility Transforms, lazy implementation or Adapter factories, and Availability
and Readiness declarations. Contract-test cases and fixtures are supplied
separately to the Contract Test Kit and are not part of the production
registration object. Adding a conforming package must not require a change to
`core/`.

Each immediate child directory under `modules/` is one discovery unit and
exports exactly one explicit registration object at
`modules/<package_name>/package.py:MODULE_PACKAGE`. Discovery scans only those
package roots and consumes that object; it does not recursively search for
arbitrary `definition.yaml` files, invoke per-Node `register()` functions, or
depend on import side effects, globs, or helper-driven resource discovery.
Helpers may construct an explicitly named resource reference but may not decide
which production resources are registered. The internal implementation and test
layout can be refined without changing this entry contract.

Discovery occurs only at startup; one atomically resolved `FrozenCatalog` is
published and remains immutable. A package entry point must not eagerly import
optional provider dependencies:
their absence is reported by availability checks. Malformed Definitions,
package import or registration failures, and conflicting contracts fail startup
atomically. ADR-0025 refines availability to the Execution Binding: a valid
Node Type remains discovered while each binding whose optional model, runtime,
accelerator, binary, or credentials are absent has its own structured
`unavailable` state. ADR-0028 defines explicit Port Type contracts, and
ADR-0029 separates startup Availability from per-Run Readiness.

The v2 boundary intentionally supports repository-owned developer extensions,
not third-party `pip install`, plugin management, runtime hot loading, or
automatic dependency installation. The Registry consumes a single Module
Package registration shape so a future Python entry-point discovery mechanism
can supply the same object without changing the package contract.

This decision supersedes ADR-0007.
