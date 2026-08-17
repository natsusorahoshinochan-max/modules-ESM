# 37 — Generate fresh source-bound remote 3GB1 evidence

> Historical completion evidence only. Checksums, symlink/security probes, Readiness-before-Cache, restart reconstruction, and old verification tiers mentioned below are not current requirements.

**What to build:** The current clean v2 source and installed backend complete a fresh canonical 3GB1 run against the required real remote providers and produce an auditable evidence bundle that cannot be replaced by readiness checks, mocks, skipped tests, Cache-only replay, or historical v1 output.

**Blocked by:** 36 — Prove installed and local-provider parity.

**Status:** completed

- [x] The gate records the exact clean source revision, installed artifact identity, public protocol digest, FrozenCatalog contract digests, Workflow revision, Contract Lock, and compile receipt before starting.
- [x] Every required remote Binding obtains a current passing Readiness Attestation, and unavailable credentials/provider state or a skipped test fails the gate.
- [x] The run crosses the declared real ESM-3 and ESMFold2 engine seams and records exact Binding, Method, adapter, source, request role, and parent-child Invocation provenance.
- [x] The complete canonical scientific assertions remain satisfied: track fidelity, ten paired ESM-3 Candidates, isolated TM-score scopes, weighted top three, 3 × 5 ProteinMPNN lineage, fifteen final folds, and fifteen retrievable PDB hashes.
- [x] Provider throttling or transient failure is represented honestly; retry uses a newly derived Run and identities rather than silently continuing or rewriting the original Run.
- [x] Cache decisions occur only after current Readiness and cannot turn a provider-free replay into proof of a required live invocation.
- [x] Every Plan Node disposition and started Attempt/Invocation terminal is present, causal references close, public replay/projection agree, and no fixed historical call count is treated as an invariant.
- [x] Artifact retrieval revalidates Project/Run scope, Port/Candidate association, media type, size, and digest against the bytes included in the evidence bundle.
- [x] The final source-bound evidence bundle contains the public receipts, safe Ledger projections, Candidate lineage, invocation proof, artifact index, checksums, and verification result needed to audit this exact v2 run.
- [x] Historical v1 evidence, mocked providers, fixture-only execution, readiness-only results, missing invocation proof, or any green skip is explicitly rejected as completion.

## Executor evidence

- Accepted base:
  `b328802198e19b1c192958d21fcaceb2857550b9`. Implementation commits:
  `3f8c0b3`, `16992dc`, and `9940727`. The first live execution completed the
  real provider work but exposed an evidence-validator receipt mismatch; the
  retained failed verification record is
  `verification-results/fresh-remote-3gb1/20260730T203652.013832Z-90242-c4f9704a15f2e0d0`.
  The mismatch was repaired without reusing that Run as completion evidence.
- Final required zero-skip clean-source gate:
  `uv run --no-sync python scripts/verify_backend.py fresh-remote-3gb1` →
  `1 passed`; retained verification and complete evidence bundle:
  `verification-results/fresh-remote-3gb1/20260730T205011.435884Z-93670-219b1c0bfa31f504`.
- The final source receipt binds clean revision
  `9940727954a6a21d9f2d490ce1f90db83ea06694`, installed wheel
  `sha256:f0c35253e4720a502e8eb7403c66b0c1e376e49ffa95829fc8073a8e7c6c6d72`,
  installed sdist
  `sha256:b4f090dffbb7926315a9e3ade08b1f7c7fcfef0bc1078616f4a3eb3e57acf12e`,
  public protocol
  `sha256:e8c8798faa1b4a1f6861e289cb1d89d302c402a28ebbec8a7b840b73ef8681ef`,
  and FrozenCatalog
  `sha256:bd6137ab032ea794870852a63c6e14dc440437c56041cca34e66277eb335074c`.
- Fresh public Run `run-56648a02511844ca8c7d274343b984b3` succeeded
  without a provider retry. The SDK was configured for one HTTP attempt, so a
  throttle/transient provider result could not be hidden inside the SDK; the
  retained gate permits retries only as a new `retry_failed` derived Run.
- Invocation proof contains 10 `sequence_parent` plus 10 one-to-one
  `structure_child` real Biohub ESM-3 invocations, 10 initial plus 15 final real
  Biohub ESMFold2 invocations with exact request roles, and three exact local
  ProteinMPNN parent invocations. All started Node Attempts, Operation Attempts,
  and Engine Invocations have one terminal, and public replay agrees with the
  terminal projection.
- Canonical assertions prove the exact pinned ProteinPrompt content and track
  positions, ten paired Candidates, ten fixed-reference and ten distinct
  paired-reference subjects in disjoint scopes, weights `0.7` and `0.3`, the
  selected top three, exactly five ProteinMPNN children per selected parent,
  fifteen final folds, and fifteen one-to-one `export-final.candidate_artifacts`
  PDBs. All 15 retained PDB digests are unique and revalidated against retrieved
  bytes, headers, public Artifact Descriptors, Project, and Run scope.
- The bundle validator passed independently against the retained final bundle,
  and `checksums.sha256` covers every public receipt, Run event replay,
  projection, lineage/proof/index file, and PDB byte file. Credential and local
  runtime paths are rejected from the bundle before checksum sealing.
- Final `/code-review`: Standards `APPROVE`; Spec `APPROVE` after repairs for
  selected-parent lineage, exact track identity, one-to-one Invocation
  provenance, and exact Artifact Port association.
- Focused fresh-gate/verifier regression:
  `12 passed, 1 deselected`. Tickets 01–37 ordinary v2 gate:
  `644 passed, 17 deselected`. Full routine gate:
  `659 passed, 30 deselected`; retained result
  `verification-results/routine/20260730T205639.458509Z-750-4886f1e2f2101d42`.
- Deterministic acceptance `8 passed`, installed artifact/public journey
  `3 passed`, repository examples `11 passed`, provider isolation `16 passed`,
  and security/failure closure `10 passed`; retained results:
  `verification-results/deterministic-acceptance/20260730T205752.554002Z-6228-95f08ae5eb1a6775`,
  `verification-results/installed-package/20260730T205818.242429Z-6642-c80b26293fabc0c1`,
  `verification-results/examples-v2/20260730T205832.662306Z-6891-3682cf83f856269d`,
  `verification-results/provider-isolation/20260730T205844.317184Z-7292-6885abed99899d3d`,
  and
  `verification-results/security-failure/20260730T205855.707047Z-7453-fb9c8869b32a9777`.

## Controller joint-test evidence

- Controller started from the previously accepted Ticket 36 gate
  `b328802198e19b1c192958d21fcaceb2857550b9` and independently tested the
  clean Ticket 37 executor revision
  `2dea39bdf13154f8946dd4975ed21c31c5788b39`.
- Controller generated a second fresh remote 3GB1 proof rather than accepting
  the executor bundle alone:
  `uv run --no-sync python scripts/verify_backend.py fresh-remote-3gb1` →
  `1 passed` in `335.10s`. The retained source-bound bundle is
  `verification-results/fresh-remote-3gb1/20260730T210657.155762Z-7897-a9a02e9db52e8069`;
  its successful public Run is
  `run-cb6a747a057f4090bf726d09edb85a66`, all sealed checksums pass, and the
  independent validator reports one Run and fifteen artifacts bound to the
  exact executor revision.
- Tickets 01–37 ordinary v2 gate passed with `644 passed, 17 deselected`.
  The full routine joint gate passed with `659 passed, 30 deselected`; retained
  result:
  `verification-results/routine/20260730T211344.463981Z-13650-9eacaa8c9027b055`.
- Deterministic acceptance passed `8/8`, installed artifact/public journey
  passed `3/3`, and the direct Biohub ESMC installed gate passed `1/1`;
  retained results:
  `verification-results/deterministic-acceptance/20260730T211503.913691Z-19102-c3f5f6e1fe5506f5`,
  `verification-results/installed-package/20260730T211536.191595Z-19521-6750d9054eaf8f3e`,
  and
  `verification-results/installed-biohub-esmc/20260730T211554.169320Z-19762-c6583e0666c54543`.
- The local ESM3, SimpleFold folding, SimpleFold confidence, SoluProt, and
  Protein-Sol installed gates each passed `1/1`; retained results:
  `verification-results/installed-local-esm3/20260730T211839.832626Z-20035-4a8d972b164b955a`,
  `verification-results/installed-simplefold-folding/20260730T212243.720143Z-20349-9a931566e588dbec`,
  `verification-results/installed-simplefold-confidence/20260730T212659.481119Z-20952-529ac8decc6ca9f5`,
  `verification-results/installed-soluprot/20260730T212718.829431Z-21495-14c85f411aef1410`,
  and
  `verification-results/installed-protein-sol/20260730T212729.790698Z-21636-ea9b5a0bff16ff8c`.
- Provider isolation passed `16/16`, security/failure closure passed `10/10`,
  repository examples passed `11/11`, scientific reproducibility passed `1/1`,
  and the independently fail-closed local ESMFold2 source contract passed
  `5/5`; retained results:
  `verification-results/provider-isolation/20260730T212739.555480Z-21754-31752be8f4dc350a`,
  `verification-results/security-failure/20260730T212746.811774Z-21899-9d5163bb69f47d83`,
  `verification-results/examples-v2/20260730T212801.069048Z-21969-3b282ebcf0aeda68`,
  `verification-results/scientific-repro/20260730T212806.874110Z-22362-e67d215b4b08276d`,
  and
  `verification-results/local-esmfold2-v2-contract/20260730T212815.349833Z-22384-8d912805195e9fd9`.
- Every retained Controller result records
  `project_revision=2dea39bdf13154f8946dd4975ed21c31c5788b39` and
  `project_dirty=false`. Controller accepts Ticket 37 and the complete
  37-ticket serial execution.
