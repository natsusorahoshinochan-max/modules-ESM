# 13 — Consolidate protein I/O

**What to build:** A Workflow can import sequence or structure data from Project-scoped inputs and export sequence or structure results as validated, Run-bound artifacts through one cohesive `protein_io` Module Package, without exposing reusable filesystem paths.

**Blocked by:** 12 — Prove the zero-Core extension journey.

**Status:** ready-for-agent

- [ ] Sequence import, structure import, sequence export, and structure export each have one v2 Node Definition and are registered by the single `protein_io` Module Package.
- [ ] Import consumes a trusted Project-scoped value or artifact reference rather than an arbitrary private host path embedded in a Workflow.
- [ ] Parsed sequence and structure values are validated, canonically encoded, content-digested, and published through exact nominal Port Types.
- [ ] Export produces opaque standalone or Candidate artifact references in Run Projection, not absolute or Run-relative path outputs.
- [ ] Artifact retrieval revalidates Project/Run ownership, output Port, artifact kind, media type, size, and digest and resists traversal, symlink, no-follow, and cross-scope reads.
- [ ] Multiple structures and Candidates retain their identities and deterministic output slots; structure exports preserve the required provider/native serialization semantics.
- [ ] Cache replay rematerializes current-Run artifacts without reusing another Run's temporary path or claiming a new scientific Invocation.
- [ ] Round-trip fixtures cover valid sequence and structure formats, malformed input, artifact tampering, cross-Run reuse attempts, and the fifteen distinct PDB export shape required by canonical acceptance.
- [ ] The package passes the shared Contract Test Kit and requires no `protein_io` special case in Core.
