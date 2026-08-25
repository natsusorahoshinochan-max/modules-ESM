# Repository Guidelines

## Priorities

This is scientific software in development. Scientific correctness and interpretability outrank compatibility and implementation concerns. Preserve semantics for Node Types, Methods, Metric Definitions, units, shapes, residue mappings, masking, randomness, lineage, provenance, and evidence. Use `CONTEXT.md` vocabulary. Resolve ambiguity in a specification or ADR; never infer science from code, SDK shapes, or UI behavior.

There is no historical compatibility obligation. Do not add shims, aliases, legacy parsers, dual paths, deprecation layers, or speculative abstractions. Change all current producers, consumers, tests, examples, and documentation together; delete superseded code. Development artifacts may be invalidated.

## Architecture

`core/` owns runtime and evidence logic. `datatypes/` defines provider-independent scientific values. Extensions live in `modules/<package>/`; provider translation belongs in Adapters. `protein_workbench_public/` owns the current protocol. Treat `repositories/` as pinned upstream.

## Trust Model

This is a trusted, single-user, loopback-only application. Components trust values after validation by their contract-owning boundary. Validate once; do not add repeated checks, authentication, authorization, multi-tenancy, adversarial handling, sandboxing, or hosted-service hardening.

Biohub and its official API specification are authoritative. Assume conforming requests receive conforming responses. Adapters must translate and record provenance exactly as documented. Do not guess schemas, repair or reject responses, cross-check providers, add fallback endpoints, or handle hypothetical malformed responses. Follow documented operational outcomes exactly.

Fail fast on local invariant violations. Avoid broad catches, silent coercion, guessed defaults, catch-and-continue behavior, and undocumented retries or fallbacks. Retain checks only for scientific correctness, explicit contracts, durable writes, accidental data loss, and credential hygiene.

## Verification

Use Python 3.12, typed code, pytest, Oxlint, and `tsc`. Test current scientific and package contracts. Mocks cannot replace required real-provider acceptance.

Run focused tests plus:

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
cd frontend && npm run lint && npm run build
```

Never commit `.local/`, `keys/`, environments, or frontend build output.
