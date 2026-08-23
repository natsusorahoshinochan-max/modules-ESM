# Acceptance and evidence simplification

Date: 2026-08-17

Status: complete; provider-free verification and the single real-Provider
Acceptance Campaign passed

This document supersedes the earlier follow-up checklist. That checklist found
real scientific gaps, but its exact inventories, directory digests, two-stage
Campaign, recovery state machine, and corruption probes imposed a threat model
that this project does not have.

## Governing requirements

1. Scientific correctness and interpretability come first. Node Types,
   Methods, units, shapes, residue mappings, masking, randomness, lineage,
   provenance, readiness, Typed Values, and Artifacts keep their specified
   meaning.
2. This is a trusted, single-user, loopback-only application. Users,
   developers, local processes, and configured Providers are assumed to follow
   the documented workflow.
3. Validate scientific and public values once at the Interface that owns the
   contract. Internal code consumes the admitted value without repeating the
   same proof.
4. Do not implement attacker handling, symlink or traversal defenses, disk
   tamper detection, permission proofs, or secret-pattern fuzzing for Evidence,
   Provider assets, or ordinary internal data. Credential files retain only the
   narrow private-regular-file check required for credential hygiene. Do not
   implement malformed Provider recovery.
5. Keep direct checks for scientific meaning, explicit public contracts,
   credential hygiene, and errors that occur on the expected path.
6. Prefer one small owner over managers, registries, state machines, policy
   objects, and parallel compatibility paths.

## Final design

### Acceptance Campaign

An Acceptance Campaign has one serial stage. `prepare` builds one wheel and
sdist from a clean revision. `run` executes the 15 canonical tiers exactly once
in order with one Execution Profile. The first failure terminates the Campaign.
There is no Qualification/Certification split, prioritization, rerun, evidence
promotion, candidate digest graph, or recovery state machine.

After implementation changes are complete, the real acceptance surface is run
once. The prior 15/15 Qualification remains useful historical diagnostic
evidence, but it is not promoted into the new Campaign.

### Retained Evidence

Each tier retains the public observations needed to inspect its successful
Runs:

```text
evidence/
  catalog-snapshot.json
  public-protocol.json
  runs/<label>/
    projection.json
    events.json
    typed-values.json
    artifacts.json
    values/*
    artifacts/*
  model-lifecycle.json   # only where the tier requires it
  tier-result.json
```

The writer copies values that the acceptance client or Service boundary has
already validated. The reader checks that required shared files and Run labels
exist. It does not enforce exact directory inventories, rescan payloads, reject
extra files, calculate a second digest, or interpret scientific conclusions.

Fresh 2EMO retains the Provider binding order already established by its public
Run events. Application-scoped Provider reuse, switching, and shutdown are
covered at the `OperationResources.local_provider` lifecycle seam rather than
by observing Provider module internals.

### Result Identity and cache

Result Identity remains the scientific cache key computed from admitted
scientific inputs and implementation identity. A cache hit replays its retained
result; a miss executes the current Binding. Internal code assumes a conforming
deterministic Binding produces the result described by its identity.

There is no second project-wide Result Identity authority, cross-Run manifest
conflict index, public `result_identity_conflict`, or restart reconstruction of
that index. Cache publication is best-effort and does not change a successful
Run conclusion.

### Objects and restart

The project object store is a small content-addressed store. It writes admitted
bytes once and reads them by their retained reference. It does not rescan
objects for mutation, stage multi-step filesystem transactions, prove owner or
mode bits, or automatically garbage-collect objects.

A terminal Run is loaded from its recorded Ledger. A Run that was still
running when the process stopped receives one honest `run_terminal` event with
status `interrupted`. Restart does not guess missing Engine, Operation, Node, or
Selection outcomes and does not synthesize a causal closure tree.

### Verification scope

The separate `security-failure` tier is removed. `routine` verifies current
scientific, public, and normal operational contracts. Required real-Provider
tests cannot be replaced by mocks. Credential values remain excluded from
Workflow, Ledger, logs, and retained Evidence.

## Scientific repairs retained from the earlier audit

- canonical 3GB1 keeps exact Provider-stage invocation counts while allowing
  legitimate local invocations;
- canonical 3GB1 retains exact readiness, alignment cardinality and mapping,
  Artifact port, filename, media, and provenance assertions;
- local ESM3 uses one union Catalog for its three Runs;
- REST ESMC retains the validated server Catalog actually used by the gate;
- all 15 tiers declare their required public Run labels;
- Evidence retention occurs only after the tier's scientific assertions pass.

## Exit criteria

- focused acceptance, cache, object, restart, and public protocol tests pass;
- `routine` and `deterministic-acceptance` pass;
- frontend lint and build pass;
- compile and diff checks pass;
- a clean revision completes one serial 15-tier real Acceptance Campaign;
- the final review finds no duplicated scientific validator, attacker-oriented
  path, compatibility layer, or brittle implementation-shape test.

## Final outcome

All exit criteria were met for source revision
`21bd098a969a0ac24d4d3de79e9020459ac13e6e`.

- The provider-free matrix passed: `routine` 1269 passed / 53 deselected;
  `examples-v2` 12 passed; `deterministic-acceptance` 8 passed;
  `scientific-repro` 1 passed; `local-esmfold2-v2-contract` 6 passed;
  `installed-package` 6 passed. The then-current `provider-isolation` tier also
  passed 16 tests; it was later removed as a defensive, non-scientific gate.
- Frontend Oxlint, TypeScript, and Vite build passed. Python compilation and
  `git diff --check` passed.
- Standards and Spec review found no remaining HIGH or MEDIUM issue.
- The one-stage Campaign at
  `verification-results/acceptance-campaign-21bd098` ran every canonical tier
  once in serial order and finished `passed` with 15/15 results.
- No second Provider run, Certification generation, Evidence promotion, or
  secondary digest was performed.

The 15/15 Campaign above remains the accepted scientific result for revision
`21bd098`. A later trust-model cleanup removed reusable Readiness proofs,
replacement/invalidation checks, whole-package inventory checks, and the
standalone `provider-isolation` tier without rerunning Providers.
