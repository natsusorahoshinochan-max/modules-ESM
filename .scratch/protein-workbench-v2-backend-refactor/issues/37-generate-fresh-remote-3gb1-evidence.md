# 37 — Generate fresh source-bound remote 3GB1 evidence

**What to build:** The current clean v2 source and installed backend complete a fresh canonical 3GB1 run against the required real remote providers and produce an auditable evidence bundle that cannot be replaced by readiness checks, mocks, skipped tests, Cache-only replay, or historical v1 output.

**Blocked by:** 36 — Prove installed and local-provider parity.

**Status:** ready-for-agent

- [ ] The gate records the exact clean source revision, installed artifact identity, public protocol digest, FrozenCatalog contract digests, Workflow revision, Contract Lock, and compile receipt before starting.
- [ ] Every required remote Binding obtains a current passing Readiness Attestation, and unavailable credentials/provider state or a skipped test fails the gate.
- [ ] The run crosses the declared real ESM-3 and ESMFold2 engine seams and records exact Binding, Method, adapter, source, request role, and parent-child Invocation provenance.
- [ ] The complete canonical scientific assertions remain satisfied: track fidelity, ten paired ESM-3 Candidates, isolated TM-score scopes, weighted top three, 3 × 5 ProteinMPNN lineage, fifteen final folds, and fifteen retrievable PDB hashes.
- [ ] Provider throttling or transient failure is represented honestly; retry uses a newly derived Run and identities rather than silently continuing or rewriting the original Run.
- [ ] Cache decisions occur only after current Readiness and cannot turn a provider-free replay into proof of a required live invocation.
- [ ] Every Plan Node disposition and started Attempt/Invocation terminal is present, causal references close, public replay/projection agree, and no fixed historical call count is treated as an invariant.
- [ ] Artifact retrieval revalidates Project/Run scope, Port/Candidate association, media type, size, and digest against the bytes included in the evidence bundle.
- [ ] The final source-bound evidence bundle contains the public receipts, safe Ledger projections, Candidate lineage, invocation proof, artifact index, checksums, and verification result needed to audit this exact v2 run.
- [ ] Historical v1 evidence, mocked providers, fixture-only execution, readiness-only results, missing invocation proof, or any green skip is explicitly rejected as completion.
