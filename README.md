# Protein Workbench

Protein Workbench is a local scientific workflow backend for protein design,
structure prediction, comparison, annotation, and scoring.

The source repository owns the
[scientific vocabulary and architectural boundaries](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/main/CONTEXT.md),
[backend verification tiers](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/main/docs/backend-verification.md),
and [backend deployment contract](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/main/docs/backend-deployment.md).
Operational documentation, repository tests, verification tooling, and Provider
source trees belong to the source checkout. Wheels contain the installable backend,
maintained Workflow examples, and package metadata. Source distributions contain
the sources needed to build that wheel and additionally carry the root lockfile;
neither artifact promises a runnable repository verification or Provider-install
workspace.

## Repository layout

- `core/` owns runtime, Workflow, Project, and evidence behavior.
- `datatypes/` owns provider-independent scientific values.
- `modules/<package>/` contains the twelve repository-owned Module Packages.
- `protein_workbench_public/` owns the current public protocol and server.
- `examples/v2/` contains maintained Workflows and their structure inputs.
- `tests/` and `verification/` own repository tests and verification tooling.
- `repositories/` contains pinned Provider sources, including the maintained
  SoluProt-next port.

Before launching the server, configure one stable absolute application data root:

```bash
export PROTEIN_WORKBENCH_DATA_ROOT="$HOME/protein-workbench-data"
```

For repository development, keep the same explicit contract while placing the
ignored state inside the checkout:

```bash
export PROTEIN_WORKBENCH_DATA_ROOT="$PWD/.local"
```

The backend derives `projects/`, `cache/`, `outputs/`, `runs/`, and Provider runtime
state from that root, so storage identity does not depend on the launch directory.
The configured value is expanded once and must be absolute. Repository verification
evidence remains separately configurable with
`PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT`.

Local ESM-3 additionally requires `PROTEIN_WORKBENCH_ESM3_MODEL_ROOT` to name the
absolute root of the already selected locked model snapshot. The backend does not
search Hugging Face cache layouts for that snapshot.
