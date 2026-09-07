# Protein Workbench WebUI

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
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The app discovers the immutable 3GB1 example,
its Workflow Draft, and its bundled completed Run through the public protocol.

Verification:

```bash
npm run typecheck
npm run lint
npm run test:e2e
npm run build
```
