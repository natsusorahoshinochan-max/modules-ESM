# Protein Workbench

Protein Workbench is a local scientific workflow backend for protein design,
structure prediction, comparison, annotation, and scoring.

The scientific vocabulary and architectural boundaries are defined in
[`CONTEXT.md`](CONTEXT.md). Backend verification commands and real-Provider
acceptance tiers are documented in
[`docs/backend-verification.md`](docs/backend-verification.md).

## Repository layout

- `core/` owns runtime, Workflow, Project, and evidence behavior.
- `datatypes/` owns provider-independent scientific values.
- `modules/<package>/` contains the twelve repository-owned Module Packages.
- `protein_workbench_public/` owns the current public protocol and server.
- `frontend/` contains the Catalog-driven React interface.
- `examples/v2/` contains maintained Workflows and their structure inputs.
- `tests/` and `verification/` own repository tests and verification tooling.
- `repositories/` contains pinned upstream Provider submodules.

Local Project state and retained verification output live under the ignored
`.local/` directory by default:

```text
.local/
  projects/
  verification-results/
```

`PROTEIN_WORKBENCH_PROJECT_ROOT` and
`PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT` may select different locations.
