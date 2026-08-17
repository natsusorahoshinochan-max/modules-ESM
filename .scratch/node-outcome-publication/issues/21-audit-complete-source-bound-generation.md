# Ticket 21 — Final lightweight scientific audit

Status: completed on 2026-08-18

After the single Campaign passes 15/15:

- [x] confirm every tier ran once in canonical order;
- [x] inspect the four source-bound scientific summaries and required lifecycle
  receipts;
- [x] confirm retained Run labels and public observations exist;
- [x] confirm no mock replaced a required Provider;
- [x] confirm no duplicate scientific validator, attacker-oriented scanner,
  compatibility layer, or implementation-shape test remains;
- [x] record the final provider-free, frontend, compile, diff, and Campaign
  results.

Do not rerun the Providers, calculate a second evidence digest, or create a new
Certification generation.

## Final audit record

- Accepted source revision:
  `21bd098a969a0ac24d4d3de79e9020459ac13e6e`.
- Campaign: `verification-results/acceptance-campaign-21bd098`, state `passed`,
  15/15 canonical tiers passed once in order.
- Installed real-Provider matrix: all 11 required tiers passed with zero skip.
- Source-bound Workflows: `fresh-1pga`, `fresh-2emo`,
  `fresh-canonical-3gb1`, and `fresh-5g53` passed their scenario-specific
  scientific assertions and retained their required public Runs. The 2EMO
  release-before-Protein-Sol observation and installed ProteinMPNN
  `load_count == 1` receipt passed.
- Provider-free matrix: `routine` 1269 passed / 53 deselected; `examples-v2`
  12 passed; `deterministic-acceptance` 8 passed; `scientific-repro` 1 passed;
  `local-esmfold2-v2-contract` 6 passed; `installed-package` 6 passed;
  `provider-isolation` 16 passed.
- Frontend Oxlint, TypeScript, and Vite build passed. Python compilation and
  `git diff --check` passed.
- Final Standards and Spec reviews reported no HIGH or MEDIUM findings.
- No Provider was rerun for this audit, no Evidence digest was added, and no
  Certification generation was created.
