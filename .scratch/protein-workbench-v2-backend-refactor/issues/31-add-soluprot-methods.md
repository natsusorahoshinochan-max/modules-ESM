# 31 — Add SoluProt Methods

**What to build:** A Workflow can score protein sequences with explicitly selected SoluProt full or no-TM Methods from one `solubility` Module Package, with independent readiness and formally identified solubility Observations.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** ready-for-agent

- [ ] The Workbench adapter is based only on the SoluProt dependency repository under the agreed external workspace and does not adopt unrelated surrounding workflow code or modify the vendor repository.
- [ ] SoluProt full and no-TM are distinct exact Methods/Bindings rather than values of a mutable `model_name` parameter.
- [ ] Shared sequence input, preprocessing, Metric Definition, adapter glue, registration, and test assets remain cohesive within the `solubility` package.
- [ ] Each Method fixes model/source/feature pipeline and scale identity, and every result is a declared Candidate/Metric/Method/intrinsic Context Observation.
- [ ] Startup Availability is lazy, and each Binding has independent per-Run Readiness; a missing full-model external dependency does not hide or block no-TM.
- [ ] Model and runtime paths are trusted Environment Configuration, resolved asset identities enter Result Identity and Invocation provenance, and stale asset replacement invalidates readiness.
- [ ] Invalid sequences, unsupported residues, preprocessing mismatch, non-finite output, or out-of-contract values fail before Observation or Cache publication.
- [ ] Actual inference creates truthful Engine Invocation evidence and retains safe, redacted diagnostics on failure.
- [ ] Golden fixtures, CTK, installed discovery, sibling-isolation tests, and required model-backed gates prove both Methods without a Core solubility branch.
