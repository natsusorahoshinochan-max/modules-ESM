# 31 — Add SoluProt Methods

**What to build:** A Workflow can score protein sequences with explicitly selected SoluProt full or no-TM Methods from one `solubility` Module Package, with independent readiness and formally identified solubility Observations.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** awaiting-controller

- [x] The Workbench adapter is based only on the SoluProt dependency repository under the agreed external workspace and does not adopt unrelated surrounding workflow code or modify the vendor repository.
- [x] SoluProt full and no-TM are distinct exact Methods/Bindings rather than values of a mutable `model_name` parameter.
- [x] Shared sequence input, preprocessing, Metric Definition, adapter glue, registration, and test assets remain cohesive within the `solubility` package.
- [x] Each Method fixes model/source/feature pipeline and scale identity, and every result is a declared Candidate/Metric/Method/intrinsic Context Observation.
- [x] Startup Availability is lazy, and each Binding has independent per-Run Readiness; a missing full-model external dependency does not hide or block no-TM.
- [x] Model and runtime paths are trusted Environment Configuration, resolved asset identities enter Result Identity and Invocation provenance, and stale asset replacement invalidates readiness.
- [x] Invalid sequences, unsupported residues, preprocessing mismatch, non-finite output, or out-of-contract values fail before Observation or Cache publication.
- [x] Actual inference creates truthful Engine Invocation evidence and retains safe, redacted diagnostics on failure.
- [x] Golden fixtures, CTK, installed discovery, sibling-isolation tests, and required model-backed gates prove both Methods without a Core solubility branch.

## Executor evidence

- Accepted base: `2f78c3d1dbd59cb7e70e911afa66e18c2b2cae7a`.
- Implementation commits: `bf2ee1e` (`feat: add exact SoluProt solubility
  methods`), `0272d27` (`fix: attest SoluProt runtime closure`), and `506bdb1`
  (`fix: close SoluProt dependency identity`).
- Dependency boundary: read-only SoluProt 1.1.0 assets under
  `/Users/sorachan/Documents/ESM-workflow-NEXT`; locked wheel SHA-256
  `71566eb9a5e78099cf82e0da55bf7f4f173c06a0c22395ba7a18324d9234db96`
  and USEARCH SHA-256
  `de3c4206a92754ba8762237b4c436ed4b72bb7bcfe287891365b47cdda0f5095`.
  The Adapter also attests the complete installed SoluProt distribution,
  direct/transitive Python distribution trees, mode-specific model assets,
  and full-mode TMHMM/Perl closure without modifying the external workspace.
- Ticket-focused/cross-slice tests:
  `uv run --no-sync pytest -q tests/test_solubility_v2.py
  tests/test_port_types_v2.py tests/test_verification_tiers.py` →
  `77 passed`.
- Cumulative v2 tests: `uv run --no-sync pytest -q tests/*_v2.py` →
  `612 passed`.
- Required model-backed gate:
  `uv run --no-sync python scripts/verify_backend.py
  soluprot-v2-local-model` → `3 passed`; retained at
  `verification-results/soluprot-v2-local-model/20260730T082252.814558Z-75033-1d2e4746b7dbfb55`.
- Routine verification: `1302 passed, 55 deselected`; retained at
  `verification-results/routine/20260730T082321.522720Z-75232-5201bb6b0974610d`.
- Deterministic acceptance: `10 passed, 5 deselected`; retained at
  `verification-results/deterministic-acceptance/20260730T082851.680666Z-83268-ecb40731b16195d4`.
- Installed-package verification: `3 passed`; retained at
  `verification-results/installed-package/20260730T083000.819296Z-83958-17e4df76f3406507`.
- Static/package checks: `git diff --check`, compileall, `uv lock --check`,
  `uv pip check`, and a zero-result case-insensitive `soluprot` search under
  `core/*.py` passed.
- Parallel `/code-review` at exact code HEAD
  `506bdb1a9541f357de50be4e8e29871502f29020`: Standards APPROVE and Spec
  APPROVE with zero remaining Critical/High/Medium findings after closing the
  full runtime dependency identity, provider-native scale contract, exact
  output precision, and safe failure reason evidence.
- Handoff boundary: executor work is complete and awaits the Controller-owned
  joint Ticket 01–31 gate; this ticket must not be marked `completed` until
  that cumulative gate passes.
