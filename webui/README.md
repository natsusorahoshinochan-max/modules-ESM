# Protein Workbench WebUI

Last updated: 2026-09-21.

Start the public v2 backend from the repository root:

```bash
PROTEIN_WORKBENCH_DATA_ROOT=/tmp/protein-workbench-data \
  .venv/bin/python -m uvicorn \
  protein_workbench_public.bootstrap:create_application \
  --factory --host 127.0.0.1 --port 8000
```

Then start the Vite application:

```bash
cd webui
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The app discovers the immutable 3GB1 example,
its Workflow Draft, and its bundled completed Run through the public protocol.
The example is read-only; its first edit creates a personal Project and preserves
the original results as an explicit reference. No Provider is needed to inspect
the bundled evidence. New Runs use the configured real Providers.

Use **添加来源** for a blank Prompt, FASTA, a PDB chain or an existing Prompt.
Batch FASTA import creates one Candidate per record. The canvas supports adding
operations, editing parameters and Selection rules, replacing connections,
copying selected fragments and undo. Run confirmation shows the actual full or
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
and the [latest complete acceptance record](../docs/2026-09-21-catalog-selection-run-acceptance.md).
The [September 19 record](../docs/2026-09-19-webui-integration-progress.md)
documents the earlier integration snapshot and the separately tracked
source-field simplification.
Set `PROTEIN_WORKBENCH_REAL_UI_URL` and `PROTEIN_WORKBENCH_REAL_FASTA_PROJECT_ID`
for the prepared service and Project, then run
`npx playwright test --config playwright.real.config.ts` on the verification host.
