# Repository Guidelines

## Project Structure & Architecture

`core/` contains the server, workflow engine, storage, and evidence logic. `datatypes/` defines provider-independent scientific values. Extensions live in `modules/<package>/` and expose one `package.py:MODULE_PACKAGE`; keep provider SDK translation inside adapters. `protein_workbench_public/` owns the versioned protocol bundle. Tests are under `tests/`, workflows under `examples/v2/`, ADRs under `docs/adr/`, and the React/TypeScript client under `frontend/src/`. Treat `repositories/` as pinned upstream source.

Use the exact domain vocabulary in `CONTEXT.md`.

## Build, Test, and Development Commands

```bash
uv sync --frozen --extra dev                    # install backend development dependencies
.venv/bin/python run_server.py                  # serve on 127.0.0.1:8000
.venv/bin/python scripts/verify_backend.py routine
.venv/bin/python scripts/verify_backend.py deterministic-acceptance
cd frontend && npm ci && npm run dev             # Vite development server
cd frontend && npm run lint && npm run build
```

Add `--extra providers` only for real provider verification. See `docs/backend-verification.md` for specialized and slow tiers.

## Coding Style & Naming

Target Python 3.12; use four-space indentation, type annotations, `snake_case` functions/modules, `PascalCase` classes, and uppercase constants. Prefer frozen dataclasses and explicit contracts. TypeScript uses two spaces, single quotes, and no semicolons; Oxlint and `tsc` are authoritative. Do not add compatibility fallbacks or hypothetical abstractions without an accepted contract.

## Testing Guidelines

Use pytest and name files/functions `test_*.py`/`test_*`. Add regressions at public or package-contract boundaries. Run the focused test plus `routine` for backend changes; run frontend lint and build for UI changes. Heavy or credentialed tiers must be intentional and cannot replace required real acceptance with mocks. No numeric coverage threshold is configured.

## Commits & Pull Requests

Use short imperative subjects, normally `feat:`, `fix:`, `test:`, `docs:`, or `refactor:`. Keep commits single-purpose. PRs must describe changed behavior, link a ticket/ADR when applicable, list verification results, and include screenshots for visible UI changes. Never commit `keys/`, `projects/`, `verification-results/`, virtual environments, or frontend build output.

## Local-Only Threat Model

This is a trusted, single-user desktop application. Keep services loopback-only; “public” means a stable component contract, not Internet exposure. Do not add authentication, RBAC, multi-tenancy, CSRF defenses, abuse controls, plugin sandboxes, or speculative hosted-service hardening. Every new safeguard must prevent a concrete non-malicious failure. Retain validation for malformed imports/provider responses, scientific and protocol correctness, accidental path or data loss, durable writes, resource exhaustion, and credential leakage. Changing the deployment model requires an explicit architecture decision.
