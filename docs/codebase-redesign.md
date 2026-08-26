# Codebase redesign: trusted scientific core

Date: 2026-08-17

## Priority order

1. Preserve scientific meaning and interpretability.
2. Keep one clear owner for each contract.
3. Trust admitted internal values and documented user workflows.
4. Prefer direct, small implementations with predictable failure behavior.

The project is single-user and loopback-only. It has no attacker model,
multi-tenant boundary, or hosted-service threat model. Do not add authentication,
sandboxing, symlink or traversal defenses, disk-tamper scanners, or permission
proofs for Evidence, Provider assets, or ordinary internal data. Credential
files retain the narrow private-regular-file boundary needed for credential
hygiene. Do not add speculative retries, fallback providers, or
malformed-response repair.

## Validation model

Scientific and public values are validated once by the Interface that owns the
contract:

- `protein_workbench_public/` owns wire payloads and events;
- `datatypes/` and Port Type admission own scientific values;
- Catalog compilation owns Node, Method, Binding, unit, shape, randomness, and
  provenance declarations;
- Provider Adapters own translation from official Provider responses;
- acceptance tests own scenario-specific scientific conclusions.

After admission, internal storage, Evidence, cache, and orchestration code trust
the value. They may serialize or copy it, but do not re-derive its meaning.

## Runtime

- A Node success publishes its admitted outputs and conclusion through one
  finalization seam.
- Result Identity is a scientific cache key, not a second global consistency
  authority.
- The cache is optional and best-effort. A miss executes the Binding.
- The object store writes admitted bytes once. It has no automatic GC or
  mutation-detection framework.
- A terminal Run reloads from its Ledger. An unfinished Run becomes
  `interrupted` on restart without reconstructing missing internal outcomes.

## Acceptance

- One Execution Profile owns configured Provider paths and remote transport.
- One Campaign builds the clean candidate and runs all 19 tiers serially once.
- The first failed tier terminates the Campaign; there is no retry or second
  Certification pass.
- Each tier asserts its own scientific contract, then retains already-validated
  public Run observations.
- Evidence has one small schema and no checksum/manifest hierarchy or recursive
  safety scanner.
- Real-Provider acceptance cannot be replaced by mocks.

The current acceptance contract is recorded in
[backend-verification.md](./backend-verification.md). The dated follow-up audit
remains evidence for its recorded revision rather than a current command source.

## Rejected designs

- repeated protocol or scientific validation after admission;
- Qualification followed by a duplicate Certification run;
- cross-Run Result Identity conflict indexes;
- restart causal reconstruction state machines;
- automatic object graph garbage collection;
- exact Evidence directory inventories and directory digest graphs;
- security-only verification tiers in this trusted application;
- AST, function-length, private call-order, or helper-count tests;
- compatibility aliases, legacy schemas, and dual implementations.

## Verification

Run focused tests, then:

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
```

After these pass on a clean revision, run one serial 19-tier Acceptance Campaign.
