# Protein Workbench

Protein Workbench provides a local scientific workflow backend and WebUI for
protein design, structure prediction, comparison, annotation, and scoring.

Use the [documentation index](docs/README.md) to find current requirements,
architecture, operations, and verification instructions. The
[confirmed requirements](docs/documentation-governance-decisions.md) define the
product behavior; the [open issues](docs/2026-10-15-documentation-governance-issues.md)
identify implementation differences and facts still needing clarification.
Documented requirements do not imply that the current application implements them.

The source repository owns the [domain vocabulary](GLOSSARY.md),
[architecture](docs/architecture.md), [backend verification entry points](docs/backend-verification.md),
and [WebUI startup and verification instructions](webui/README.md).
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

- `core/` owns runtime, Workflow, Project, and necessary execution records.
- `datatypes/` owns shared provider-independent values; it does not limit the types modules may declare.
- `modules/<package>/` contains repository-owned Module Package sources. External modules follow the same extension contract; the current fixed assembly and missing installer remain implementation gaps.
- `protein_workbench_public/` owns the current public protocol and server.
- `examples/v2/` contains maintained Workflows, structure inputs, and bundled WebUI results.
- [`webui/`](webui/README.md) contains the React WebUI; its production build is deployed separately from the backend wheel.
- `tests/` and `verification/` own repository tests and verification tooling.
- `repositories/` contains pinned Provider sources, including the maintained
  SoluProt-next port.
- `docs/` contains current requirements, reference documentation, and unresolved issues.
- `.scratch/` contains ignored, local-only experiments and prototypes.
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
