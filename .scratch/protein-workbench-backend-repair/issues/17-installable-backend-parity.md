# 17 — Ship an installable backend with source-checkout parity

**What to build:** A maintainer can build and install the Protein Workbench backend in a clean environment and obtain the same required Module discovery, canonical Workflow validation, and API startup behavior as the source checkout.

**Blocked by:** 16 — Execute the canonical 3GB1 Workflow to fifteen auditable PDB artifacts.

**Status:** completed

- [x] The built artifact contains all backend Python packages and every YAML ModuleDefinition required for discovery.
- [x] Required ModuleDefinition or registration failures are visible startup and test failures rather than silently skipped modules.
- [x] Runtime, WebSocket, provider, model/checkpoint, and development/test dependencies are captured by a reproducible install contract.
- [x] Vendor repositories remain read-only and are not treated as package-owned repair surfaces.
- [x] An isolated installed-package smoke discovers the expected Modules, loads and validates the canonical Workflow, and starts the API without source-tree-only assets.
- [x] Installed-package smoke results are retained as an explicit acceptance gate.
