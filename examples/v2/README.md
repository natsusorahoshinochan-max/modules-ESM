# Protein Workbench v2 examples

`repository-capabilities.workflow.json` is a provider-free-to-verify authoring
example: it fixes exact Node Type and Execution Binding versions, separates
Node and Binding parameters, and locks only its reachable Catalog closure.
Verification parses, relocks, and compiles the Workflow but does not invoke any
provider.

`capability-inventory.json` records the accepted production Node Type identities
from the eleven cohesive Module Packages. Run:

```bash
uv run --no-sync python -m examples.v2_suite
```

The exact multi-objective scoring example is Contract Test Kit support under
`tests/fixtures/v2_workflows`; it deliberately depends on independent
deterministic fixture Observations and Utilities and is not shipped as a
production capability.
