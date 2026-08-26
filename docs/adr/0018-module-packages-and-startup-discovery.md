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

The Catalog builder admits repository-owned registrations once while constructing
the startup `FrozenCatalog`. It validates stable-ID uniqueness, required
references, implementation or Adapter resolvability, Port compatibility,
Candidate and Observation subjects, Metric schemas, residue-axis relationships,
dependency closure, and the other relationships that directly protect scientific
module inputs and outputs. Build and focused tests exercise this same builder.

Discovery occurs only at startup; one admitted `FrozenCatalog` is published and
remains immutable. Catalog construction does not compute repository-owned
descriptor digests, Contract Locks, semantic versions, or installation identity.
A package entry point must not eagerly import optional provider dependencies;
their absence is reported by diagnostic Availability observations.

Package import, stable-ID/reference/factory, or scientific-relationship failures
fail startup. A diagnostic `unavailable` Binding remains registered and can still
proceed to fresh Run-scoped Readiness; Availability never rejects execution.
ADR-0025 assigns that diagnostic to the Execution Binding, ADR-0028 defines Port
Type scientific contracts, and ADR-0029 defines Readiness before actual Provider
entry.

The extension boundary supports repository-owned developer extensions,
not third-party `pip install`, plugin management, runtime hot loading, or
automatic dependency installation. The Registry consumes exactly one Module
Package registration shape.
