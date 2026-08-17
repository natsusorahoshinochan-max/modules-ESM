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
- symlink, traversal, permission, object-address, and secret-pattern probes;
- automatic object GC;
- project-wide Result Identity conflict authority;
- restart reconciliation events and inferred attempt terminals;
- exact nested Evidence inventories and orphan-payload rejection;
- implementation-shape and AST tests.

## Required final verification

1. focused provider-free tests;
2. `routine`;
3. `deterministic-acceptance`;
4. frontend lint and build;
5. compile and diff checks;
6. one clean-revision, serial, real-Provider Acceptance Campaign covering all
   15 tiers.

The previous 15/15 Qualification is retained only as historical diagnostic
evidence. It is not copied into the new single-stage Campaign.
