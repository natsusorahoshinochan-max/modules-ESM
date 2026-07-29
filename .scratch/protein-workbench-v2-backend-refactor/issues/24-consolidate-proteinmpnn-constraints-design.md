# 24 — Consolidate ProteinMPNN constraints and design

**What to build:** A Workflow can author complete ProteinMPNN constraints, reproducibly choose random fixed positions, and design multiple child sequences per selected parent through one cohesive `proteinmpnn` Module Package with exact model identity and lineage.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** in-progress

- [ ] Constraint authoring, random fixed-position selection, and sequence design each have one v2 Node Definition under the single `proteinmpnn` package registration.
- [ ] Constraint values cover designable and fixed positions, designed and fixed chains, omitted amino acids, tied positions, and per-residue bias with explicit layout/chain validation.
- [ ] Random fixed-position selection records an effective seed and all result-affecting parameters, uses no process-global randomness, and changes Result Identity when randomness changes.
- [ ] The design Binding fixes the exact ProteinMPNN Method/model/checkpoint/source and adapter/implementation identity; `model_name`, model path, device, and runtime directories are not free Workflow parameters.
- [ ] Startup Availability and per-Run Readiness validate package/runtime/model prerequisites without eager model loading or a Core provider map.
- [ ] Structure, collection, optional sequence, and constraints inputs normalize into one declared design contract without losing parent Candidate identity.
- [ ] Each selected parent produces the requested complete number of child Candidates with stable parent/output/sample/content lineage, effective randomness, and no cross-parent identity collision.
- [ ] Provider output and optional scores are validated before publication; partial children, missing parent relationships, or malformed sequences fail the Node without caching.
- [ ] Deterministic tests prove the canonical three-parent by five-child shape, constraint fidelity, replay stability, actual Engine Invocation, CTK conformance, and installed discovery.
