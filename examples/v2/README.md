# Protein Workbench v2 examples

`repository-capabilities.workflow.json` is a provider-free-to-verify authoring
example: it fixes every production Execution Binding that can be connected
using production values, separates Node and Binding parameters, and locks only
its reachable Catalog closure. Verification parses, relocks, and runs the
compiler's complete static checks but does not invoke any provider. An installed
artifact without a selected provider must reach the compiler's explicit
`binding_unavailable` conclusion; no sibling Binding is selected.

`capability-inventory.json` records the accepted production Node Type identities
from the eleven cohesive Module Packages. Run:

```bash
uv run --no-sync python -m examples.v2_suite
```

The remaining production Bindings are covered through locked Contract Test Kit
Workflows under `tests/fixtures/v2_workflows`: exact prompt-track inputs cover
the two track transformations, and exact fixed-3GB1/paired-ESM3 Observations and
Utilities cover all six selection operations. Those independent fixtures are
not shipped as production capabilities.
