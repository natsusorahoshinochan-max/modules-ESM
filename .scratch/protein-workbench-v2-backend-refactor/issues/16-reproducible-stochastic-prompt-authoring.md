# 16 — Make stochastic prompt authoring reproducible

**What to build:** A Workflow author can randomly mask or insert masked residues while obtaining explicit effective randomness, stable replay semantics, and residue-aligned prompt tracks suitable for deterministic canonical acceptance.

**Blocked by:** 14 — Consolidate residue layout and track editing.

**Status:** ready-for-agent

- [ ] Random masking and masked insertion are registered as `prompt_authoring` Nodes with exact input/output Port contracts and no process-global random state.
- [ ] Every execution resolves and records an effective seed and all result-affecting random parameters before computing Result Identity.
- [ ] Repeating exact inputs and effective randomness produces byte-equivalent canonical outputs; changing the seed or any stochastic parameter changes Result Identity.
- [ ] Uncontrolled randomness or an unresolvable effective seed disables cross-Run caching rather than producing an incomplete Cache key.
- [ ] Masking changes only the declared track positions and preserves layout length, chain boundaries, nullable values, and untouched tracks.
- [ ] Insertion updates layout, residue maps, and every affected track consistently and rejects impossible counts, positions, or layout constraints.
- [ ] Fixtures cover zero/full masks, repeated positions, chain boundaries, inserted masked sequence and secondary-structure tracks, and stable replay after Cache materialization.
- [ ] The canonical 3GB1 masking and insertion intent is captured as an ordinary regression rather than by relying on historical random call order.
- [ ] Both Nodes pass the shared CTK and public execution path without package-specific scheduler or Cache logic.
