# Redesign switch: lightweight acceptance evidence

Date: 2026-08-17

Status: switched

This switch replaces the earlier defensive Acceptance prototype with the
trusted scientific design in [codebase-redesign.md](./codebase-redesign.md).

## Active structure

```text
Acceptance Campaign
  prepare clean wheel + sdist
  run 15 canonical tiers once, serially
    scientific assertions
    retain validated public observations
  passed | failed | interrupted
```

Retained Evidence contains one Catalog snapshot, the public protocol used by
the acceptance client, required public Runs, and the small lifecycle receipt
only for tiers that need it. It does not contain per-file manifests, checksum
trees, source receipts, a second protocol validator, or a generic lifecycle
state machine.

## Trust rules

- users and developers follow the documented workflow;
- configured Providers follow their official contracts;
- internal components trust values after the owning boundary admits them;
- failures outside this model are not represented by additional code;
- credential values remain private;
- scenario-specific scientific assertions remain exact.

## Removed

- dual Qualification and Certification stages;
- rerun and prioritization policy;
- Campaign identity/digest graph and evidence mutation checks;
- `security-failure` verification tier;
- symlink, traversal, permission, object-address, and secret-pattern probes for
  Evidence, Provider assets, and ordinary internal data; credential-file
  privacy remains the narrow credential-hygiene exception;
- automatic object GC;
- project-wide Result Identity conflict authority;
- restart reconciliation events and inferred attempt terminals;
- exact nested Evidence inventories and orphan-payload rejection;
- implementation-shape and AST tests.
- reusable Readiness proof, age, fingerprint, and invalidation state;
- whole-package inventory, clean-checkout, no-follow, and staged-copy rehash
  gates;
- the standalone `provider-isolation` verification tier.

## Required final verification

1. focused provider-free tests;
2. `routine`;
3. `deterministic-acceptance`;
4. frontend lint and build;
5. compile and diff checks;
6. one clean-revision, serial, real-Provider Acceptance Campaign covering all
   15 tiers.

Revision `21bd098` subsequently completed the required one-stage Campaign with
15/15 tiers. That scientific result remains accepted; the later provider-free
trust-model cleanup did not rerun Providers.
