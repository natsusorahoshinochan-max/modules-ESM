# Protein Workbench

Protein Workbench provides a local scientific workflow backend and WebUI for
protein design, structure prediction, comparison, annotation, and scoring.

The source repository owns the
[scientific vocabulary and architectural boundaries](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/main/CONTEXT.md),
[backend verification entry points](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/main/docs/backend-verification.md),
and [WebUI startup and verification instructions](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/main/webui/README.md).
Operational documentation, repository tests, verification tooling, and Provider
source trees belong to the source checkout. Wheels contain the installable backend,
maintained Workflow examples, and package metadata. Source distributions contain
the sources needed to build that wheel and additionally carry the root lockfile;
neither artifact promises a runnable repository verification or Provider-install
workspace.

## Deployment and verification

The application can be deployed on machines that satisfy the software, hardware
and Provider requirements of the selected operations. It is not tied to the
repository's remote verification host. The supported deployment model remains
a trusted, single-user application bound to loopback on the chosen machine.

The backend requires Python 3.12 and its declared dependencies. WebUI development
and builds additionally require Node.js and npm; the built WebUI is deployed
separately from the backend wheel. Remote Provider operations require their SDK
and credentials, while local model operations require their configured model
files, native tools and supported device resources. Browsing bundled results
does not require running those Providers. Sufficient memory or GPU capacity
alone does not establish operating-system compatibility for every Provider.

Repository contributors run automated verification on the designated remote
host under the backend verification policy. This is a development workflow,
not a requirement that users deploy on that host. See the WebUI instructions
linked above for installation, startup and built-asset deployment.

## Repository layout

- `core/` owns runtime, Workflow, Project, and evidence behavior.
- `datatypes/` owns provider-independent scientific values.
- `modules/<package>/` contains the repository-owned Module Packages.
- `protein_workbench_public/` owns the current public protocol and server.
- `examples/v2/` contains maintained Workflows, structure inputs, and bundled WebUI results.
- [`webui/`](https://github.com/natsusorahoshinochan-max/modules-ESM/blob/main/webui/README.md) contains the React WebUI; its production build is deployed separately from the backend wheel.
- `tests/` and `verification/` own repository tests and verification tooling.
- `repositories/` contains pinned Provider sources, including the maintained
  SoluProt-next port.
- `.scratch/` contains ignored, local-only experiments and prototypes. Durable
  design decisions belong in `docs/`; prototype files are not committed.
- `.local/` contains ignored backend Run data, temporary generation results, and
  fixture-production intermediates.
- `webui/test-results/` contains ignored Playwright test results.

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
absolute root of the configured complete `esm3_sm_open_v1` snapshot. The backend
does not search Hugging Face cache layouts for that snapshot.
