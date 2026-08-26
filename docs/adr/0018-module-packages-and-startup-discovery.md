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
which production resources are registered. Internal implementation and test
layout do not change this entry contract.

Repository-owned registrations pass their complete scientific relationship gate
during build and test. That gate validates Port compatibility, Candidate and
Observation subjects, Metric schemas, residue-axis relationships, dependency
closure, and other rules that directly protect scientific module inputs and
outputs. It produces or admits the typed registrations consumed at runtime.

Discovery occurs only at startup; one `FrozenCatalog` is published and remains
immutable. Runtime discovery checks only the minimum invariants needed to start:
stable IDs are unique, required registrations are present, and implementation or
Adapter factories resolve. It does not recompute repository-owned descriptor
digests, Contract Locks, semantic versions, or the complete scientific
relationship gate on every startup. A package entry point must not eagerly
import optional provider dependencies; their absence is reported by diagnostic
Availability observations.

Package import failures and violations of the minimum runtime registration shape
fail startup. A diagnostic `unavailable` Binding remains registered and can
still proceed to fresh Run-scoped Readiness; Availability never rejects
execution. ADR-0025 assigns that diagnostic to the Execution Binding, ADR-0028
defines Port Type scientific contracts, and ADR-0029 defines Readiness before
actual Provider entry.

The extension boundary supports repository-owned developer extensions,
not third-party `pip install`, plugin management, runtime hot loading, or
automatic dependency installation. The Registry consumes exactly one Module
Package registration shape.
