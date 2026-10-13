# Protein Workbench WebUI

Last updated: 2026-10-13.

The approved canvas experience is now the default application at `/`. There is
one entry and build (`npm run dev`, `npm run build`); the prototype entry,
mode, banner, layout switcher and right inspector have been removed.

- Open published output collections directly from a node or stage card.
- Results identifies the exact source and can locate it in the canvas. Saving a
  Selection keeps the current results and offers navigation to the new nodes.
- Prompt Studio shows its project, group and owning node. G/R previews update
  locally while moving; confirmation submits the final transform.
- The operation palette remains collapsible. Focus, comparison and checked
  candidates remain independent in Results.

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
Set the required environment variables before starting the backend. Paths are
absolute and belong to the deployment machine:

| Operation | Required configuration |
| --- | --- |
| Browse and edit the bundled example | Backend and WebUI dependencies; no model invocation |
| Biohub ESMC, ESM-3 and ESMFold2 | `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE`, pointing to a private credential file, plus network access |
| Local ESM-3 | `PROTEIN_WORKBENCH_ESM3_MODEL_ROOT` with the complete model snapshot |
| Local ESMFold2 | `PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT` and `PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT` |
| SimpleFold | `PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT`, `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT`, `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT` |
| ProteinMPNN | `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` |
| DSSP | `PROTEIN_WORKBENCH_MKDSSP_BINARY` |
| SoluProt | `PROTEIN_WORKBENCH_SOLUPROT_ROOT`, containing the prepared Provider runtime and tools |
| Protein-Sol | `PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT`, plus Bash and Perl on `PATH` |

Local Providers also require their supported platform, device, memory and native
tools. For example, full SoluProt additionally requires Perl. The current mapping
is owned by [provider_environment.py](../protein_workbench_public/provider_environment.py);
setting a directory variable does not install the Provider. Missing model
configuration prevents the corresponding operations from running, not browsing
already published example results. Credentials must remain outside Git.

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
verification, not to where users may install or run the application. Historical
machine paths in acceptance records identify evidence locations only.

## Application behavior

See the [design and verification history](../docs/research/2026-10-05-canvas-prototype.md).

Open `http://127.0.0.1:5173`. The app discovers the immutable 3GB1 example,
its Workflow Draft, and its bundled completed Run through the public protocol.
The example is read-only; its first edit creates a personal Project and preserves
the original results as an explicit reference. No Provider is needed to inspect
the bundled evidence. New Runs use the configured real Providers.

The default example opens as five ordered stage groups:
**模板 → Prompt (4) → 生成候选与初筛 (7) → 首轮折叠与筛选 (11) →
设计序列 (2) → 末轮折叠与筛选 (11)**, followed by the ordinary export node.
The 36 computation nodes and 61 edges remain unchanged; 14 connections cross
stage boundaries, including two references from the first validation stage to
the final stage. The groups form one horizontal row at an initial 100% zoom.
Stage navigation and horizontal panning keep cards readable; Fit View is an
explicit overview action.

Stage controls map directly to existing node parameters and open the existing
Prompt or Selection editors; they do not duplicate values or merge independent
seeds. See the [stage and parameter mapping](../docs/research/2026-09-29-default-example-grouping.md).
Browsing the immutable example does not create a copy. Its first edit preserves
the displayed grouping, positions, per-level views and parameter mappings in the
new personal Project's UI state. Existing personal copies are not migrated or
automatically rearranged. Remote frontend verification passed: 70 focused cases, followed by five browser
regressions after the final control-position adjustment. Application/test types,
lint and build passed; the interaction contract records snapshots and viewport
coverage. The user confirmed stage acceptance on 2026-09-29. The October 6 update adds local G/R display while dragging; confirmation still uses the backend preview.

Use **添加来源** for a blank Prompt, FASTA, a PDB chain or an existing Prompt.
Batch FASTA import creates one Candidate per record. The canvas supports adding
operations, editing parameters and Selection rules, replacing connections,
nested node groups, independent group copies, and undo/redo. See the
[current frontend interaction contract](../docs/2026-09-29-frontend-interaction-contract.md)
for matrix keys, 3D navigation and selection, group navigation, and the current
stage acceptance record. Structure transforms now update selected atom coordinates locally on animation frames. Enter or left-click submits the final transform to the backend preview and accepts one edit; Escape or right-click restores the starting coordinates. This October 6 change is separate from the earlier grouping acceptance. The viewer uses 3Dmol.js directly. Run confirmation shows the actual full or
partial scope. Continuation forces the selected Nodes and descendants to execute
and refuses missing reusable upstream results.

Results expose published intermediate stages, exact Scores and parents,
side-by-side views and existing alignment evidence. Temporary grouped filters,
ranking and checked Candidates can become ordinary editable Workflow operations.
ZIP export includes FASTA, Scores and provenance; only Candidates with structures
receive PDB files. Project management persists Drafts, layout and named versions,
including returning to the work that preceded opening an old version.

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
[real FASTA journey specification](../docs/2026-09-19-webui-fasta-journey-spec.md)
and the [latest complete acceptance record](../docs/2026-10-07-frontend-full-acceptance.md).
The [September 19 record](../docs/2026-09-19-webui-integration-progress.md)
documents the earlier integration snapshot and the separately tracked
source-field simplification.
Set `PROTEIN_WORKBENCH_REAL_UI_URL` and `PROTEIN_WORKBENCH_REAL_FASTA_PROJECT_ID`
for the prepared service and Project, then run
`npx playwright test --config playwright.real.config.ts` on the verification host.
