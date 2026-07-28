# 21 — Unify remote and local ESMFold2 folding

**What to build:** A Workflow can fold a protein sequence with an explicitly selected remote or local ESMFold2 Binding of one shared folding Node Type and receive complete structure Candidates plus canonical `[0,100]` pLDDT Observations.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** ready-for-agent

- [ ] One folding Node Definition owns the cross-Binding scientific inputs, outputs, and parameters; remote and local ESMFold2 are explicit Bindings rather than separate scientific Node Types.
- [ ] Each Binding fixes its execution route, Method, model/source identity, adapter/implementation identity, Readiness, determinism, and cacheability without a mutable `model_name`.
- [ ] Credentials, endpoint, local model path, device, and runtime settings are injected through trusted Environment Configuration and do not enter Workflow parameters.
- [ ] Neither Binding is selected or substituted by Availability; unavailable local execution leaves the remote Binding discoverable and vice versa.
- [ ] ESMFold2 native `[0,1]` per-residue pLDDT is statically multiplied by 100 and exposed as `structure.plddt.per_residue`; `structure.plddt.mean_residue` is the equal-weight mean over valid protein residues only.
- [ ] Padding, chain breaks, non-protein tokens, and NaN are excluded from the mean; pTM remains `[0,1]`, PAE remains in angstroms, and no observed-range scale guessing is used.
- [ ] Every sample yields a complete, validated structure Candidate with stable parent/sample/content lineage and exact Produced Observations.
- [ ] Readiness precedes Cache, actual folding crosses a declared Engine Invocation seam, and decode or normalization failure cannot publish a successful Candidate.
- [ ] Differential provider-native fixtures plus required remote and local gates prove scale, completeness, no fallback, source-bound evidence, and CTK conformance.
