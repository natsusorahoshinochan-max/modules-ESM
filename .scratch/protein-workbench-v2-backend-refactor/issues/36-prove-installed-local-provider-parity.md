# 36 — Prove installed and local-provider parity

**What to build:** A clean installed backend exposes the same v2 contracts as the source checkout and successfully exercises every required repository-owned local or remote-provider extension through the shared package, readiness, evidence, Cache, and public protocol seams.

**Blocked by:** 35 — Remove the legacy v1 runtime.

**Status:** completed

- [x] A production artifact is built and installed outside the source checkout, and backend acceptance imports and launches only that artifact.
- [x] Source and installed deployments resolve byte-identical protocol bundles, canonical descriptors, Contract digests, FrozenCatalog contracts, and stable Catalog identity while keeping Availability observations separate.
- [x] Every required Definition, Metric resource, adapter/runtime resource, and behavior declaration is packaged, while package-local tests, fixtures, and the synthetic echo package are excluded.
- [x] The installed public journey covers Catalog, Workflow save/compile, Readiness, Start/Cancel/Derived Run, replay/live events, Projection, Cache replay, and Artifact Retrieval without importing internals.
- [x] A required zero-skip installed gate invokes exact Biohub `esmc-600m-2024-12` through a direct ESMC Node/Binding, public protocol, Run Evidence Ledger, Readiness, and two declared Engine Invocations; it returns the provider mean embedding and validates the sequence-logits shape without fixtures, source imports, direct-SDK test bypass, or parallel evidence.
- [x] Required zero-skip gates also exercise all local ESM-3 generation modes, SimpleFold folding, exact-asset SimpleFold confidence, SoluProt full/no-TM, and Protein-Sol multiple-Metric output.
- [x] Local ESMFold2 remains an independently registered fail-closed sibling and keeps its deterministic source contract, but local ESMFold2/ESMC snapshots and 6B shards are not required by the installed zero-skip completion gate; remote ESMFold2 remains explicitly distinct from direct Biohub ESMC.
- [x] Each gate proves an actual declared Engine Invocation, exact Method/Binding and asset identities, current Readiness, produced Candidate/Observation contracts, complete terminal evidence, and source-bound artifacts where applicable.
- [x] Mutation and sibling-isolation cases cover changed credentials, binary/model/data artifacts, configuration fingerprints, missing optional dependencies, and stale readiness without hiding unaffected Bindings.
- [x] Cumulative failure/security tests cover path containment, no-follow, ownership/mode, symlink resistance, redaction, bounded diagnostics, process cleanup, project/run isolation, cache conflicts, and evidence failure.
- [x] Unavailable, skipped, fixture-only, no-Invocation, source-importing, contract-mismatched, or legacy-fallback results fail the required gate rather than producing green acceptance.

## Executor evidence

- User-directed provider override: local ESMC/ESMFold2 heavy inference is not
  a completion requirement. Direct Biohub ESMC is the required installed
  zero-skip route; local ESMFold2 remains an independently fail-closed sibling
  with a deterministic provider-free source contract.
- Accepted base: `80bb70dd95bc7a9ca20142bcaaf00ca723bbb053`.
  Implementation commits before the provider override: `56e5ad1`, `f7c3984`,
  `329b7a2`, and `06b173d`; final direct-Biohub-ESMC implementation commit:
  `3ffd719`.
- The direct Node/Binding/Method invokes exact Biohub
  `esmc-600m-2024-12` through public Workflow/Run protocol and records distinct
  `encode` and `logits` Engine Invocations. It validates a 1152-dimensional
  binary32 mean embedding and sequence logits shaped `[L+2, 64]`.
- Final `/code-review`: Standards APPROVE and Spec APPROVE.
- Executor gates: routine `656 passed`; installed package `3 passed`; direct
  Biohub ESMC, local ESM-3, SimpleFold folding, SimpleFold confidence,
  SoluProt, and Protein-Sol each `1 passed`; provider isolation `16 passed`;
  security/failure `10 passed`; deterministic acceptance `8 passed`; examples
  `11 passed`; scientific reproduction `1 passed`; local ESMFold2 source
  contract `5 passed`.
- Executor retained results include:
  `verification-results/installed-biohub-esmc/20260730T193740.744312Z-65738-5b7a637f13354071`,
  `verification-results/routine/20260730T194055.922990Z-66035-44025f29340f687e`,
  `verification-results/installed-package/20260730T194117.695994Z-71127-ff98e4ee6ba6ffc8`,
  `verification-results/installed-local-esm3/20260730T194427.943530Z-72216-b2e990f0be482b03`,
  `verification-results/installed-simplefold-folding/20260730T194819.933508Z-72457-ebc436b04eb7184d`,
  `verification-results/installed-simplefold-confidence/20260730T195244.486966Z-72643-01f425bfc229919c`,
  `verification-results/installed-soluprot/20260730T195303.764182Z-73057-67eb1890f927d292`,
  `verification-results/installed-protein-sol/20260730T195313.301829Z-73182-44199828254ad9eb`,
  and
  `verification-results/provider-isolation/20260730T195324.219501Z-73302-ce7edb1f6a1059a3`.
- Executor handoff SHA `3ffd719408217406b1e8af806e67078373ab7384`
  was clean and Ticket 37 was not started.

## Controller joint-test evidence

- Previous accepted multi-ticket gate:
  `80bb70dd95bc7a9ca20142bcaaf00ca723bbb053`; independently tested Ticket 36
  executor SHA: `3ffd719408217406b1e8af806e67078373ab7384`.
- Tickets 01–36 ordinary v2 gate:
  `uv run --no-sync pytest -q tests/*_v2.py` →
  `641 passed, 16 deselected`; tier-specific cases are exercised below.
- Full routine joint gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `656 passed, 29 deselected`; retained result
  `verification-results/routine/20260730T200050.207526Z-78047-5da4d281b9fbfd68`.
- Clean installed-artifact parity and public journey:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260730T200117.609807Z-82993-43ca8b02502ecc9c`.
- Direct installed Biohub ESMC:
  `uv run --no-sync python scripts/verify_backend.py
  installed-biohub-esmc` →
  `1 passed`; retained result
  `verification-results/installed-biohub-esmc/20260730T200137.271561Z-83195-653f022d0b164633`.
- Installed local ESM-3:
  `uv run --no-sync python scripts/verify_backend.py installed-local-esm3` →
  `1 passed`; retained result
  `verification-results/installed-local-esm3/20260730T200244.607708Z-83330-e46daed6542d3781`.
- Installed SimpleFold folding and confidence:
  `uv run --no-sync python scripts/verify_backend.py
  installed-simplefold-folding` →
  `1 passed`; retained result
  `verification-results/installed-simplefold-folding/20260730T200657.152790Z-83554-3fde86b747d981a7`;
  `uv run --no-sync python scripts/verify_backend.py
  installed-simplefold-confidence` →
  `1 passed`; retained result
  `verification-results/installed-simplefold-confidence/20260730T201138.426935Z-83804-fcb7d307f511f328`.
- Installed SoluProt and Protein-Sol:
  `uv run --no-sync python scripts/verify_backend.py installed-soluprot` →
  `1 passed`; retained result
  `verification-results/installed-soluprot/20260730T201157.951784Z-84283-f182ca41fb955bbd`;
  `uv run --no-sync python scripts/verify_backend.py installed-protein-sol` →
  `1 passed`; retained result
  `verification-results/installed-protein-sol/20260730T201211.317651Z-84409-3f17043d74cb1bb3`.
- Provider mutation/sibling isolation:
  `uv run --no-sync python scripts/verify_backend.py provider-isolation` →
  `16 passed`; retained result
  `verification-results/provider-isolation/20260730T201225.252494Z-84551-98d373fae4a0f114`.
- Security and failure closure:
  `uv run --no-sync python scripts/verify_backend.py security-failure` →
  `10 passed`; retained result
  `verification-results/security-failure/20260730T201239.732983Z-84707-4a7f09b2802c3ff5`.
- Deterministic acceptance, repository examples, scientific reproduction, and
  local ESMFold2 provider-free source contract respectively passed
  `8`, `11`, `1`, and `5` tests; retained results:
  `verification-results/deterministic-acceptance/20260730T201356.868740Z-84794-da148726b66bb1b9`,
  `verification-results/examples-v2/20260730T201421.091775Z-85244-3ff6ec08369225cd`,
  `verification-results/scientific-repro/20260730T201431.794936Z-85637-4ef4bf499db77351`,
  and
  `verification-results/local-esmfold2-v2-contract/20260730T201441.838503Z-85655-3d7df3fa7498d52a`.
- All 14 retained Controller records report
  `project_revision=3ffd719408217406b1e8af806e67078373ab7384` and
  `project_dirty=false`. The worktree was clean before this evidence-only
  status update, and no installed/source, provider, security, or cross-ticket
  regression was found.
