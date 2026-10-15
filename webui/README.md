# Protein Workbench WebUI

The application has one entry at `/`. This guide describes how to start the
current implementation and verify frontend changes. Product requirements and
implementation gaps are maintained in the [workspace](../docs/workspace.md),
[results](../docs/results.md), and [Prompt editing](../docs/prompt-editing.md)
specifications, under the [current governance decisions](../docs/documentation-governance-decisions.md).

## Install and start on your machine

Use Python 3.12 for the backend and Node.js 22.12 or later with npm for the
frontend toolchain. The commands below use a POSIX shell and run from a source
checkout. On other systems, use the corresponding virtual-environment executable
paths and environment-variable syntax; availability of each native dependency
and local Provider must be checked for that platform.

From the repository root, create the backend environment and install the package:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
export PROTEIN_WORKBENCH_DATA_ROOT="$HOME/protein-workbench-data"
.venv/bin/protein-workbench-server --host 127.0.0.1 --port 8000
```

Choose one persistent absolute data directory for this installation. Personal
Projects, Drafts, results and runtime state are stored there; do not use a
throwaway temporary directory for work you intend to retain.

In a second terminal, start the frontend:

```bash
cd webui
npm ci
npm run dev -- --host 127.0.0.1
```

Vite forwards `/api` HTTP and WebSocket traffic to `http://127.0.0.1:8000`.
If the backend uses another port, configure the target when starting Vite:

```bash
PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1
```

The backend must also be started with the matching `--port`. No fixed SSH
server, account, port forwarding or machine-specific filesystem path is required.

## Provider configuration

Install Provider Python dependencies when you need model execution:

```bash
.venv/bin/python -m pip install -e '.[providers]'
```

This installs Python dependencies, not model weights or all external executables.
The current implementation reads configuration from environment variables before
backend startup. Follow [Provider configuration](../docs/provider-configuration.md#当前配置入口)
for each selected route's credentials, absolute paths on the backend machine,
native tools and required platform/device. Setting a directory variable does not
install the Provider. Missing model configuration prevents the corresponding
operations from running, not browsing already published example results.
Credentials must remain outside Git.

An application settings interface is a confirmed requirement: modules declare
their settings, and the carrier displays, saves and supplies them. It is not yet
provided by the environment-variable path above. See [Provider configuration](../docs/provider-configuration.md)
for the current setup and its gap from that requirement. Model downloads and
automatic environment installation are outside this decision; per-calculation
parameters remain in Node/Binding controls.

## Deploy built frontend assets

Build the frontend with `npm ci` and `npm run build` from `webui/` on a suitable
build machine. Deploy the resulting `webui/dist/` alongside a backend installation;
the Python wheel does not contain these frontend assets. Node.js is not needed
merely to serve the built files.

Configure a loopback HTTP server to serve `dist/` and reverse-proxy `/api` to the
loopback backend, preserving the path and supporting WebSocket upgrades for Run
events. Both must appear under the same browser origin. Vite's
`PROTEIN_WORKBENCH_BACKEND_URL` setting configures the development proxy only;
it does not configure the server that hosts `dist/`. Keep the application within
its trusted single-user, loopback deployment model.

The repository's remote-only build and test policy applies to contributor
verification, not to where users may install or run the application.

## Application behavior

Open `http://127.0.0.1:5173`. The current app discovers the protected 3GB1 teaching
example, its Workflow Draft and bundled completed Run through the public protocol.
No Provider is needed to inspect these results; new Runs use configured real
Providers. The [example resource guide](../examples/v2/README.md#protected-webui-result-resource)
describes what ships in the backend package.

The canvas exposes operations, Node/Binding parameters, connections, nested
groups, independent group copies and undo/redo. Default stage cards map to real
nodes and parameters; groups preserve the actual workflow dependencies.
[Workspace behavior](../docs/workspace.md) defines these interactions and the
confirmed manual-save, project-copy and tutorial rules.

Prompt Studio combines a residue matrix and structure view. G/R moving and
rotation update temporary coordinates locally; Enter or left-click confirms the
final backend preview, and Escape or right-click restores the starting state.
The viewer uses 3Dmol.js. Confirmation of an edit and persistent project saving
have separate requirements; see [Prompt editing](../docs/prompt-editing.md).

Results browse published intermediate outputs, exact Scores, parents and available
alignment results. Focus, export selection and same-Run comparison are independent.
The current ZIP exporter writes FASTA, Scores, metadata and PDB files for Candidates
that have structures. [Results](../docs/results.md) defines the required history,
reuse, structure formats, viewers and parameter export behavior.

The current application still differs from confirmed requirements: it saves on
edits/navigation, copies the teaching example on first edit, mainly opens the
latest Run, retains result-to-workflow actions, and lacks mmCIF export and complete
module settings/viewer integration. These are implementation gaps, not endorsed
usage rules. Full historical/cross-project input adoption and source-independent
availability remain to be verified. Project-wide editing protection
during execution and batch result retention/continuation also require changes.
Node-level continuation currently forces selected Nodes and descendants to run;
it is distinct from the required continuation of unfinished requests within a
batch. See [execution](../docs/execution.md) and the [governance issue list](../docs/2026-10-15-documentation-governance-issues.md).

## Verification

For read-only review and explanatory text/link changes, inspect content and
references without running executable verification. For behavior changes, use
the complete [backend execution policy and gates](../docs/backend-verification.md#execution-policy)
and these frontend entry points. This document records commands, not a claim
that the current working tree has passed them.

Run all verification on the remote verification host, reusing its existing
Python 3.12 `.venv` and installed frontend dependencies. Do not run tests or builds
on the local workstation. From the remote snapshot's `webui/` directory:

```bash
npm run typecheck
npx tsc --noEmit --strict --skipLibCheck --target ES2023 \
  --module ESNext --moduleResolution Bundler --allowImportingTsExtensions \
  --jsx react-jsx --esModuleInterop --types node \
  playwright.real.config.ts real-tests/*.ts
npm run lint
npm run test:e2e
npm run build
```

The standalone `tsc` command checks the real Provider journey configuration and
tests; `npm run typecheck` does not include `real-tests/`.

The regular Playwright configuration uses an isolated backend on port 8180 and
Vite on port 5179. Real Provider journeys have a separate
`playwright.real.config.ts`; they require an explicitly supervised built WebUI
service and the prepared FASTA Project. See the
[real FASTA journey procedure](../docs/backend-verification.md#real-fasta-webui-journey)
for preparation, report collection and its required original full Run identity.
Set `PROTEIN_WORKBENCH_REAL_UI_URL` and `PROTEIN_WORKBENCH_REAL_FASTA_PROJECT_ID`
for the prepared service and Project, then run
`npx playwright test --config playwright.real.config.ts` on the verification host.
